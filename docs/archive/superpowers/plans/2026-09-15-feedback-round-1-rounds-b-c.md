# Feedback Round 1 — Rounds B and C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Feedback Round 1 on branch `feedback-r1`.
- **Round B (UI, WP7–WP12):**
  - Today's header: reminders move to `/reminders`, a FilterBar, and one system-notes fold.
  - A case header that shows figures only.
  - A durable, audited phone number.
  - Settings as forms, with a DB-backed Users tab.
  - A greeting.
  - The weekly figures served.
- **Round C (WP5, WP6):**
  - The PEAK API door, as a port with an honest state.
  - A calendar with personal notices and moving a next action.

**Architecture:** Round A (WP1–WP4) is built on the same branch. These tasks read what it serves (`payment_position`, `payment_summary`, the PEAK pipeline, notes and attachments).
- Backend work adds FastAPI routes and SQLAlchemy-core stores in the `records` schema, each audited and role-gated.
- Frontend work mounts on the existing screens under the density ratchets.
- Five planners cut the five clusters independently. The controller's pre-flight scan below orders them into waves.

**Tech Stack:** Python 3.9, FastAPI, SQLAlchemy core, PostgreSQL (`landing` / `app` / `audit` / `records`); React 18, Vite, vitest.

**Spec:** `~/Documents/Obsidian Vault/Debt modules (self build)/10 - Feedback Round 1 - Design.md` §3 WP5–WP12, §4 F9–F19, §5, §9.
- The repo copy is `docs/archive/superpowers/specs/2026-09-15-feedback-round-1-design.md` (WP text identical; §9 lives in the vault note).
- Arina approved F1–F19 as recommended, and on 2026-09-15 approved every remaining step without further gates.

## Global Constraints

- **Baseline** (Round A final, head `ff5c8f1`, `scripts/verify_all.sh` EVERYTHING PASSED): backend 1,046 passed / 11 skipped; frontend 743 passed / 63 files; e2e 31 of 31.
- **Authority:** Requirements Amendment v2.6 §1. The design note above is binding over this plan, and the SDD ledger's rulings amend it.
- **Test contract:** a pre-existing (pinned) test changes only as a numbered edit, measured first, with the comment `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`.
  - Edit 36 is B1, 37 is B2b, 38 is the case-page density fixtures after B7b, and 39 is C3a.
  - Edits 40 and up are taken only when a further measured edit is unavoidable, each recorded in the ledger. Edit 17 stays reserved.
  - Adding tests is free.
- **Density ratchets:**
  - `frontend/src/density.test.jsx` caps the case page at 109 / 128 until edit 38 sets the measured numbers.
  - `frontend/src/today-density.test.jsx` caps Today at 31 per row, 112 chrome and 1,662 per 50-row page.
  - Every screen task measures before and after with the served blocks present, and pastes the census lines.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns, including sums across served rows.
- **REQ-COL-075:** `payment_status` keeps its five values. `payment_status` and `dc_status` stay two fields. `StatusPair` is not modified.
- **PKD-001:** `backend/app/integrations/peak.py` keeps exactly four public functions and stays DRAFT_ONLY. It is never imported or edited; C1 adds a new module.
- **Raw-body uploads only.** `python-multipart` is not installed.
- **Honesty rules:**
  - A configured-but-unreachable dependency refuses; an unconfigured one is labelled.
  - Every refusal is an RFC 9457 problem with `message_th`. In `routers/today.py`, `problem_from` fills `errors[0]` only when the CaseError carries `pointer=`.
  - Indicative figures are badged.
  - Nothing falls back silently; an unknown query value is a 422.
- **PDPA:**
  - A phone number lives only in `records.customer_contact` and is never logged; audit detail says set or cleared, never the number.
  - E-mail addresses appear only in `records.user_account`, the audit subject and the audit actor.
  - The PEAK 13-digit id is never stored.
  - `AUTH_MODE` is never written into `backend/.env`.
  - Test-account passwords are never printed.
- **Every write route** is role-gated where the design names a role, and audited before any side effect that can raise. Sign the actor with `who(body, x_volt_officer)`; `officers.sign` returns a tuple.
- **Strings:** new text goes in a flat `i18n-*.js` table, EN and TH. Grep every new key across all four tables first, because `i18n.test.js` does not catch a same-table overwrite.
- **Python:** 3.9-safe.
- **CSS:** real tokens only (`--ink-*`, `--line-default`, `--caption-12`, `--label-13`, `--body-strong-14`), literal px, no hex.
- **Frontend patterns:**
  - `SearchSelect` gets `className`, `labelClassName` and `triggerClassName`.
  - Async effects carry an unmount guard.
  - A busy act button keeps focus: `aria-disabled` plus an early return, never native `disabled` on the focused control.
  - A live region is mounted empty, then filled (R5-E04).
  - A vitest `api` mock returns a Promise from every binding called at mount.
  - `rerender` re-wraps `PrefsProvider`.
  - Today keys `CaseContactDrawer` by customer uid.
- **Worktree rules:**
  - Work in `/Users/parattakorn/volt-debt-worktrees/feedback-r1` and run `backend/.venv/bin/python -m pytest` without `-q`.
  - Each task uses the `VOLT_TEST_PG_URL` database the controller assigns. Never set `DATABASE_URL` to `volt_local`.
  - Never use a bare `git stash`. Never revert a tracked file to prove RED; use a scratch copy or a monkeypatch. Never cd into `/Users/parattakorn/volt-debt-prototype`.
  - Commit with a message file and a pathspec (`git commit -F <file> -- <paths>`). The message ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W`. Never `git add -A`.

## Build order

The controller's pre-flight scan (ledger, `.superpowers/sdd/2026-09-15-feedback-round-1-rounds-b-c/progress.md`) sets the waves. Each cluster section below states its own internal order and cross-cluster dependencies. B14 is BLOCKED until another session's weekly overview is committed to `design-team`.

---



<!-- ===== cluster section: P1-wp7.md ===== -->

## WP7 — Today and the board header (planner P1: Tasks B1, B3, B2a, B2b, B4)

**Work package:** design §3 WP7; decisions F10 (a) "one folded หมายเหตุระบบ per screen; refusals stay reachable" and F11 (a) "`/reminders` now, the calendar later".

**Tasks, in build order** (B1 and B3 give elements back before B2b spends them):
- **B1** — the reminder batch leaves Today (list and board) for `/reminders`. Frontend.
- **B3** — the standing notices fold into one "หมายเหตุระบบ (n)" on Today, Recovery and InvoicePipeline. Frontend.
- **B2a** — `GET /v1/today` gains `tier`, `payment_status`, `dc_status`, `product`, `q` (and validates `officer`); unknown values are 422; `meta.tier_counts` and `meta.officer_totals` are served. Backend only. May run in parallel with B1/B3 (disjoint files).
- **B2b** — the tier strip, the officer select and the "whole team today" panel become the Work Book's `FilterBar`. Frontend. Needs B1 and B3 committed (same file, `Today.jsx`) and B2a's key names (its tests use fixtures, so B2a need not be merged first).
- **B4** — the Today density measure. Measure only, no test edit.

**Deviations from note 11's headers, measured, and why.**
1. **No rail row for `/reminders` (B1).** A rail row costs a numbered edit in `Shell.test.jsx` (the `TH_ORDER`/`ROUTES` arrays at `:24-28`/`:30` and the EN list at `:67-73`), and C3 would spend a second one replacing it with ปฏิทิน. B1 instead puts one link on Today's header (+1 element) and names `/reminders` in the trail (`Shell.jsx` `findActiveRail`), so a closed rail never shows the case page's crumbs on it.
2. **B2 is split** into B2a (backend) and B2b (frontend), each testable alone.
3. **`api.test.js` costs 0** (design §5 said 1 line): B1 keeps the `api.reminders` / `api.sendReminder` bindings unchanged; only the screen that calls them moves.
4. **The design's "keep `data-tier-code` on the filter options" is not possible**: `SearchSelect` renders its options only while open (`SearchSelect.jsx:140`). The tier-anchor pins are re-targeted to the open list under edit 37.
5. **The officer control keeps its label "แสดงงานของ"** (`today.officer`), not the design's "เจ้าหน้าที่": the same control, the same word, and `Today.test.jsx:399` keeps passing untouched because `getByLabelText('แสดงงานของ')` finds the `SearchSelect` trigger through its `aria-labelledby`.
6. **Recovery's "eight" notices:** of the eight `<Notice>` sites in `Recovery.jsx`, four are standing screen rules and fold (`:285` cashRule, `:353` feeNote, `:460` cashRule, `:461` pathNote). Four stay on their card because they are facts about that case, not notices: `:448` the recorded outcome, `:658` the buyback figure with its PendingBadge, `:663` "deed not executed", `:681` the restructure entry gate (read inside `restructure-figures` by `Recovery.test.jsx:175`).

**Measured numbers (vitest census of `frontend/src/today-density.test.jsx`, run on scratch copies of `frontend/src`):**

| state | chrome (cap 112) | per row (cap 31) | 50-row page (cap 1,662) |
|---|---|---|---|
| HEAD (`b5bdc7c`, identical to `caddc4b` for every file below) | 112 | 31 | 1,662 |
| after B1 | 108 | 31 | 1,658 |
| after B1 + B3 | 105 | 31 | 1,655 |
| after B1 + B3 + B2b | **104** | **31** | **1,654** |

Block costs measured on the density fixture (visible elements): reminder fold shut 5; Today→/reminders link 1; tier strip 29; officer `<label>` + `<select>` with 2 options 4; dial-disabled line 3; "why these counts differ" fold shut 2; `SystemNotes` fold shut 2; `FilterBar` with five `SearchSelect`s (6 each) + bar + search box 32; team-workload fold shut (leads only) 4.

The density fixture does not serve what B2a adds, so B4 re-runs the same census on a scratch fixture that does (`tier_counts`, `officer_totals` + note, `counts_note_th`, `ptp_history_note_th`, one answer waiting elsewhere):

| served-extras fixture | HEAD | after B1–B3 |
|---|---|---|
| OFFICER, unfiltered | 114 / 31 / 1,664 | 104 / 31 / 1,654 |
| OFFICER, `?tier=ROUTINE` | 114 / 31 / 1,664 | 105 / 31 / 1,655 |
| MANAGER on "ทุกคน" | 119 / 32 / 1,719 | 105 / 32 / 1,705 |

(The MANAGER row's 32 per row is the pre-existing officer name on each row in "ทุกคน" mode; the ratchet measures OFFICER.) **Every cap holds; no cut and no density edit is needed.**

**Pins (measured at HEAD) — two numbered edits in this section, 0 elsewhere:**

| edit | task | file:lines | what moves |
|---|---|---|---|
| 36 | B1 | `Today.test.jsx:272-304` (1 test, 33 lines) | moved to `Reminders.test.jsx`; 3 lines change in the copy (`:273` render target, `:274` hero wait removed, `:301` second `/v1/today` call removed) |
| 36 | B1 | `Today.test.jsx:481-485` (5 lines of the test at `:473-486`) | moved to `Reminders.test.jsx`; `:474-480` (`offsetsLabel`) stay |
| 36 | B1 | `round4.test.jsx:196-203` (1 test, 8 lines) | moved to `Reminders.test.jsx` with its `offsets_conflict` fixture; 1 line changes (render target) |
| 37 | B2b | `Today.test.jsx:196-203` | 7 tier chips → tier filter options |
| 37 | B2b | `Today.test.jsx:266-269` | `<select>` value/options → trigger `data-value` / open list |
| 37 | B2b | `Today.test.jsx:445` | `toHaveValue` → `data-value` |
| 37 | B2b | `Today.test.jsx:453` | `fireEvent.change` → open + pick |
| 37 | B2b | `Today.test.jsx:490`, `:503` | fixture gains `tier_counts`; chip count → option label |
| 37 | B2b | `Today.test.jsx:508-509`, `:512-518` | fixture gains `tier_counts`; chip loop → option loop |
| 37 | B2b | `round4.test.jsx:661-663`, `:667-668` | per-officer calls/buttons → `officer_totals` / options |
| 37 | B2b | `round4.test.jsx:766` | `fireEvent.change` → open + pick |

Edit 37 totals: 8 tests in 2 files (6 in `Today.test.jsx`, 2 in `round4.test.jsx`), 31 original lines. Edit 36 totals: 2 whole tests + 1 split test in 2 files, 46 lines moved, 4 lines changed. The controller may renumber 36/37 against the other clusters; if the budget is short, both are one reason (WP7: the batch, the strip and the panel left Today's face) and can share one number.

Pins measured and held at **0**: `api.test.js:17,19,29`; `InvoicePipeline.test.jsx:102` (a `role="status"` inside a shut native `<details>` is still found by `getByRole` in jsdom — probed); `Recovery.test.jsx:175,186,188`; `Today.test.jsx:390-400` (pick-officer focus), `:446` (`count-note`), `:504`, `:520-521`, `:591-596` (`ptp-history-note`), `:611-676` (`refusal-od04`, its id, the `<th>` marks); `round4.test.jsx:506-518` (`answers-elsewhere-go` href); every test in `Today.board.test.jsx`; `Shell.test.jsx` (no rail row added); `today-density.test.jsx` (under every cap).

**Shared files** (every file here that another cluster may also touch):
- **`frontend/src/screens/Today.jsx`** — B1, B3, B2b. HEAD line map of what this section edits:
  - B1: `:29-32` comment; `:123-133` `offsetsLabel` (→ re-export); `:164` `reminders` state; `:292-300` `loadReminders`; `:402-412` `sendReminder`; `:503-505` and `:554-563` reminder locals; `:643-704` `remindersBlock`; `:817` (link inserted before the refresh button); `:972`, `:1143` mounts.
  - B3: `:15` imports; `:568-582` comment; `:786-795` the `page-note` fold in the header; `:821-832` pick-officer `Notice`; `:974-1001` bands, dial line, PTP note (list); `:1112-1121` board caption; `:1151-1160` board bands + seeding fold; a new `systemNotes` const inserted before `return (` at `:747`.
  - B2b: `:15` imports; after `:57` constants; `:164-172` workload state; `:208` `officerSelect`; `:232`, `:264` the load call and its deps; `:283-290` lead effect; `:368-400` `loadWorkload`; after `:463` `onFilter`; `:500` early return; `:603-641` `tiersBlock`; `:706-745` `workloadBlock`; `:763` sub line (filtered mark); `:811-816` officer label + select; after `:819` the `FilterBar` mount; `:971`, `:973`, `:1142`, `:1144` mounts; inside B3's `systemNotes`.
  - **Not touched:** the hero, `QueueRow`, `HeroActions`, `ContactActions` calls, `BoardView`, `BoardCard`, `Strip`, and the `CaseContactDrawer` mount with `key={drawerFor.customer.uid}` (`:1164-1185`).
  - **P2 / B7** (dial buttons use the phone override) meets this section at `noPhoneRows` (`:519`) and the `dial-disabled-why` line, which B3 moves into `systemNotes` — sequence B7 after B3 and edit the line where B3 put it. **P3 / B12** (greeting) edits `:751` (`<h1>`) beside B2b's `:763` sub-line mark — no overlap in lines, but sequence the two, not in parallel.
- **`frontend/src/App.jsx`** — B1 `:6` import, `:104` route. P5 / C3 adds `/calendar` and retires `/reminders`.
- **`frontend/src/components/Shell.jsx`** — B1 `:81-84` (`SUB_PAGES` in `findActiveRail`). P5 / C3 adds the ปฏิทิน rail row and removes the `/reminders` entry.
- **`frontend/src/i18n-today.js`** — B1 and B2b add keys after `:164` (EN) and `:753` (TH). **`frontend/src/i18n-journey.js`** — B3 adds one key after `:387` / `:821`.
- **`frontend/src/screens/Today.test.jsx`**, **`frontend/src/round4.test.jsx`** — edits 36 (B1) and 37 (B2b). P3 / B12 may price a title pin in `Today.test.jsx`.
- **`frontend/src/screens/Reminders.jsx`**, **`Reminders.test.jsx`** — created by B1; P5 / C3 retires them (its header prices `Reminders.test.jsx` at 1).
- **`frontend/src/components/FilterBar.jsx`** (`:12`, `:26`) and **`SearchSelect.jsx`** (`:16`, `:22`) — B2b, additive props; WorkBook and Payments consume them unchanged.
- **`frontend/src/realign.css`** — B3 after `:187`.
- **`frontend/src/screens/Recovery.jsx`**, **`InvoicePipeline.jsx`** (+ their test files, appended) — B3.
- **`backend/app/routers/today.py`** — B2a `:145-152` only. P2 / B6 adds a phone route in the same file; no line overlap.
- **`backend/app/today.py`** — B2a `:52`, `:186-190`, `:206-221`, `:225`, `:294`. P4 / B13's `reports.weekly()` calls `build()` with no arguments; B2a keeps that call's items identical (additive meta keys only).
- **`frontend/src/today-density.test.jsx`** — B4 reads it; no edit.

**Depends on:** nothing from another cluster. **Others depend on this section:** P5 / C3 on B1 (`Reminders.jsx`, its test, the `/reminders` route, `SUB_PAGES`); P2 / B7 on B3 (where the dial line lives).

### Global constraints (copied from the Rounds B/C brief; every task below carries them)

- **Baseline to beat (at caddc4b):** backend 1,022 passed / 11 skipped, frontend 726 passed / 63 files, e2e 31 of 31 (`scripts/verify_all.sh`). HEAD has since moved to `b5bdc7c` (PEAK and attachment fixes, none in this section's files) and the worktree carried another session's uncommitted work while this plan was measured, so **every task re-measures its own baseline in its first step** and reports counts as that baseline plus its additions.
- **Test contract:** a pinned (pre-existing) test changes only as a numbered edit 36–39. The edit must be measured first. It carries a comment `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`. Adding tests is free. Say in each task which pins it touches, with the file:line and the measured number, or "0".
- **Density ratchets:**
  - `frontend/src/density.test.jsx` caps the case page at 109 pre-contact / 128 worked. Its fixtures carry a served `payment_summary` and a stale `payment_position`.
  - `frontend/src/today-density.test.jsx` caps Today at 31 per row, 112 chrome, 1,662 per 50-row page.
  - Every screen task measures before and after, and pastes the census lines. A task that would exceed a cap either cuts, or spends a numbered edit with the measured number. Say which, in the plan.
  - A density fixture that does not carry the block a task adds does not measure it. The measure step must serve the block in a scratch copy.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns. That includes sums across served rows.
- REQ-COL-075: `payment_status` keeps its five values. `payment_status` and `dc_status` stay two fields. `StatusPair` is not modified.
- PKD-001: `backend/app/integrations/peak.py` keeps exactly four public functions and stays DRAFT_ONLY. C1 adds a NEW module and never imports or edits `peak.py`.
- **Raw-body uploads only.** `python-multipart` is not installed, so an `UploadFile` parameter stops the app booting.
- **Honesty rules:**
  - A configured-but-unreachable dependency refuses; an unconfigured one is labelled.
  - Every refusal is an RFC 9457 problem with `message_th`. In `routers/today.py`, `problem_from(exc)` only fills `errors[0]` when the CaseError carries a `pointer=` extra.
  - Indicative figures are badged. Nothing falls back silently; that includes an unknown query value, which is a 422, not ignored.
- **PDPA:**
  - A phone number is stored only in its `records` table and never logged. Audit detail carries "set"/"cleared", not the number.
  - E-mail addresses appear only in the user-account table and the audit subject.
  - The PEAK 13-digit id is never stored.
  - `AUTH_MODE` is never written into `backend/.env`. Test-account passwords (`~/.volt-test-accounts.json`) are never printed.
- **Every write route is role-gated where the design names a role, and audited** (`audit.describe(act=…, subject=…, detail=…)`) before any side effect that can raise.
  - Sign the acting person with `who(body, x_volt_officer)` from `routers/today.py`.
  - `officers.sign` returns a TUPLE `(by, by_role)`, so never compare it to a string.
- **Strings:** user-facing text goes in `frontend/src/i18n-*.js`. Each file is two FLAT objects (`TODAY_EN`/`TODAY_TH`, `OPS_EN`/`OPS_TH`, `ADMIN_EN`/`ADMIN_TH`, `JOURNEY_EN`/`JOURNEY_TH`), never `prefs.jsx`'s `DICT`. `i18n.test.js` checks parity, `{slots}` and cross-table collisions, but NOT a same-table overwrite. Every new key is grepped across all four tables first, and the plan says so.
- **Python:** 3.9-safe (no `match`, no runtime `X | Y`).
- **CSS:** real tokens only. `tokens.css` has `--ink-*`, `--line-default`, `--caption-12`, `--label-13`, `--body-strong-14`. It has no `--space-*`, `--radius-*` or bare `--line`. Use literal px for spacing and no hex literals.
- **Frontend patterns that bit Round A:**
  - `SearchSelect` must get `className`, `labelClassName` and `triggerClassName`, like Payments.jsx:101-115.
  - Async effects need an unmount/`alive` guard.
  - A vitest `vi.mock('../api.js')` object must return a Promise from every binding the component calls at mount.
  - `rerender` must re-wrap `PrefsProvider` or it remounts.
  - Role in tests: `window.localStorage.setItem('volt.role', …)` or `setRole` from `components/role.jsx`.
  - Today mounts `CaseContactDrawer` with `key={drawerFor.customer.uid}`.
- **Backend patterns:**
  - `/v1/workbook` and both CSV exports share `_workbook(...)`.
  - Server-side sort keys live in its `keyfn` map.
  - The run registry's finished state is `"done"`, with result fields at the top level.
  - `X-Volt-Filename` must be `urllib.parse.unquote`d before sanitising.
- **Worktree rules for implementers (put them in each task):**
  - The backend interpreter is `backend/.venv/bin/python`; run pytest without `-q`.
  - Each task names its own `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<db>?host=/Users/parattakorn/.volt-postgres/data`. The controller assigns the database; write `<task-db>`.
  - Never set `DATABASE_URL` to `volt_local`. Never use a bare `git stash`. Never cd into `/Users/parattakorn/volt-debt-prototype`.
  - Commit with a message FILE plus a pathspec: `git commit -F <file> -- <paths>`. The message ends with the two lines `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W`.
  - Never `git add -A`.

- **This section's own rules:**
  - Frontend commands run from `frontend/` (`npx vitest run ...`). Backend commands run from `backend/` as `VOLT_TEST_PG_URL="postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data" .venv/bin/python -m pytest ...` (no `-q`; `pytest.ini` already adds it).
  - Before the first edit of every task, run `git log --oneline -3` and `git status --short`. If `Today.jsx`, `Today.test.jsx`, `round4.test.jsx`, `i18n-today.js`, `today.py` or `routers/today.py` is dirty or has moved since this plan, stop and tell the controller: another session is in the file.
  - A known order trap, measured at HEAD: running `tests/test_round4.py ... tests/test_round1_p3.py tests/test_audit_middleware.py` as a hand-picked subset fails three `test_audit_middleware.py` tests. The full suite and that file alone both pass. Judge the backend by the full suite.

---

### Task B1: The reminder batch leaves Today for `/reminders`

**Files:**
- Create: `frontend/src/screens/Reminders.jsx` (the block from `Today.jsx:643-704`, its loader `:292-300`, its sender `:402-412`, its locals `:503-505` + `:554-563`, and `offsetsLabel` `:123-133`)
- Create: `frontend/src/screens/Reminders.test.jsx`, `frontend/src/App.reminders.test.jsx`, `frontend/src/components/Shell.reminders.test.jsx`
- Modify: `frontend/src/screens/Today.jsx` (`:29-32`, `:123-133`, `:164`, `:292-300`, `:402-412`, `:503-505`, `:554-563`, `:643-704`, `:817`, `:972`, `:1143`)
- Modify: `frontend/src/App.jsx:6` (import), `:104` (route)
- Modify: `frontend/src/components/Shell.jsx:81-84` (`findActiveRail`)
- Modify: `frontend/src/i18n-today.js:164` (EN), `:753` (TH)
- Modify (edit 36): `frontend/src/screens/Today.test.jsx:272-304`, `:481-485`; `frontend/src/round4.test.jsx:196-203`

**Interfaces:**
- Consumes: `api.reminders({ days: 7 })` → `{ reminders: [{customer_uid, display_name, volt_id, due_on, kind, overdue, officer_uid}], meta: {total, horizon, offsets, batch_label, offsets_conflict, template_th, note_th, note} }` and `api.sendReminder({ customer_uid, channel: 'LINE', note })` — both unchanged (`api.js:237-238`).
- Produces:
  - `screens/Reminders.jsx`: `export function offsetsLabel(offsets, batchLabel) -> string` (moved verbatim) and `export default function Reminders()`.
  - `screens/Today.jsx`: `export { offsetsLabel } from './Reminders.jsx'` (so `Today.test.jsx:9`'s import keeps working).
  - Route `/reminders` → `<Reminders />`.
  - Test ids kept verbatim on the page: `reminders` (the `<details>`, now `open`), `reminder-offsets`, `reminder-template`, `reminder-note`, `offsets-conflict`, `offsets-conflict-note`, `[data-reminder-day]`, `[data-reminder]`. New: `today-reminders-link` (Today header).
  - `rememberOrigin` record from the page: `{ for: '/customers/<uid>', path: '/reminders', screenKey: 'today.remindersPage.title', … }`.
  - `Shell.jsx`: `SUB_PAGES = { '/reminders': { group: 'nav.myWork', label: 'today.remindersPage.title' } }`, read first by `findActiveRail`.
  - i18n keys (i18n-today.js, both tables): `today.remindersLink`, `today.remindersPage.title`, `today.remindersPage.sub`.
- Behaviour change on the page (deliberate): when the batch read fails, the page shows the refusal and no longer also says "ไม่มีแจ้งเตือนค้างส่ง".

**Pins:** edit 36 — `Today.test.jsx:272-304` (1 test, 33 lines, moved; 3 lines change), `Today.test.jsx:481-485` (5 lines, moved), `round4.test.jsx:196-203` (1 test, 8 lines, moved; 1 line changes). `api.test.js`: 0. `Shell.test.jsx`: 0. Density: chrome 112 → **108**, row 31 → 31, page 1,662 → **1,658** (measured).

- [ ] **Step 1: Re-measure the baseline**

Run: `git log --oneline -3 && git status --short`, then from `frontend/`: `npx vitest run 2>&1 | tail -4` and `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected: the frontend count (paste it; 726 / 63 files at `caddc4b`, more at later heads); the census prints `TODAY  chrome=112  perRow=31  at 50 rows=1662`.

- [ ] **Step 2: Grep the new keys and the new test ids first**

Run: `grep -n "today.remindersLink\|today.remindersPage\|today-reminders-link" src/i18n-*.js src/screens/*.jsx src/components/*.jsx`
Expected: no output (no table and no screen already uses them).

- [ ] **Step 3: Write the failing tests**

`frontend/src/screens/Reminders.test.jsx` (create):

```jsx
// Feedback Round 1, WP7 / F11 (a): the D-3/D0 reminder batch left Today (list and
// board) for its own page, /reminders, until the calendar (C3) takes it in. Same
// component, same endpoint, same test ids — so the three pinned tests that read the
// batch on Today moved here with their assertions intact (AUTHORISED TEST EDIT 36).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setOfficer, setRole } from '../components/role.jsx'
import Reminders from './Reminders.jsx'
import TodayScreen from './Today.jsx'

vi.mock('../api.js', () => ({
  api: {
    today: vi.fn(), todayItemDone: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(),
    dictionary: vi.fn(), logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(),
  },
}))

const Page = () => <MemoryRouter initialEntries={['/reminders']}><Reminders /></MemoryRouter>

// Shaped like GET /v1/today/reminders (today.py): due date then name, D-3 for a
// future due date, D0 for today, overdue when the date has passed.
const REMINDERS = {
  reminders: [
    { customer_uid: 'cu-9', display_name: 'ลูกค้าทดสอบ 0196', volt_id: '99999000105_VOLT', due_on: '2026-10-20', kind: 'D0', overdue: true, officer_uid: 'nantapol' },
    { customer_uid: 'cu-2', display_name: 'อารีย์ พงษ์ไพบูลย์', volt_id: 'C-000912_VOLT', due_on: '2026-10-26', kind: 'D-3', overdue: false, officer_uid: 'noon' },
    { customer_uid: 'cu-1', display_name: 'ลูกค้าทดสอบ 0187', volt_id: '99999000112_Kun_VOLT', due_on: '2026-10-26', kind: 'D-3', overdue: false, officer_uid: 'nantapol' },
  ],
  meta: {
    total: 3, horizon: '2026-10-30',
    template_th: 'เรียนคุณ {name} ค่างวดเดือนนี้ {amount} บาท ครบกำหนดวันที่ {due} ชำระผ่าน QR ในใบแจ้งหนี้ได้เลยค่ะ',
    note: 'a reminder is a notification, not a collection contact — it never spends the daily slot',
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  setRole('OFFICER')
  setOfficer('nantapol')
  api.reminders.mockResolvedValue(REMINDERS)
  api.sendReminder.mockResolvedValue({ contact: { uid: 'ct-9' }, case: {} })
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
})

describe('Reminders — the batch on its own page', () => {
  // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
  // Today.test.jsx:272-304 rendered <Today /> → renders <Reminders />. The batch left
  // Today (design WP7, F11 a). Three lines moved with it: the hero wait (this page has
  // no hero), and `api.today` called twice (this page has no desk to reload). Every
  // other assertion is the original, unchanged.
  it('shows the next seven days of reminders grouped by due date, with the template, and marks one sent', async () => {
    const { container } = renderIn('th', <Page />)
    await waitFor(() => expect(api.reminders).toHaveBeenCalledWith({ days: 7 }))
    const strip = await screen.findByTestId('reminders')
    await waitFor(() => expect(strip.querySelectorAll('[data-reminder-day]').length).toBe(2))
    const days = [...strip.querySelectorAll('[data-reminder-day]')].map((d) => d.getAttribute('data-reminder-day'))
    expect(days).toEqual(['2026-10-20', '2026-10-26'])
    // The day heading is dd/mm/yyyy; the overdue row says so; the kind is in words.
    expect(strip.querySelector('[data-reminder-day="2026-10-26"] .td-reminders__day')).toHaveTextContent('26/10/2026')
    const overdue = strip.querySelector('[data-reminder="cu-9"]')
    expect(overdue).toHaveTextContent('วันครบกำหนด')
    expect(overdue).toHaveTextContent('เลยกำหนด')
    const d3 = strip.querySelector('[data-reminder="cu-2"]')
    expect(d3).toHaveTextContent('ก่อนครบกำหนด 3 วัน')
    expect(d3.querySelector('.td-overdue')).toBeNull()
    expect(strip.querySelector('[data-reminder-day="2026-10-26"]').querySelectorAll('[data-reminder]').length).toBe(2)
    // What the message says, and that it never spends the daily slot.
    expect(within(strip).getByTestId('reminder-template')).toHaveTextContent('เรียนคุณ {name} ค่างวดเดือนนี้ {amount} บาท')
    // N2-12: the known English note reads as Thai on the Thai screen.
    expect(within(strip).getByTestId('reminder-note')).toHaveTextContent('ไม่ใช้สิทธิ์ติดต่อรายวัน')
    expect(within(strip).getByTestId('reminder-note')).not.toHaveTextContent('never spends')
    // Round 5, ruling 75 (label pass edit 16, E2): "ส่งแล้ว" was a past-tense
    // state — the SOP's own word for it (§3, "บันทึกว่าส่งแล้ว") — sitting on the
    // button that SENDS. Moved to "ส่งแจ้งเตือน", lifted verbatim from
    // `case.sendReminder`, the same api.sendReminder call on CustomerCase.
    fireEvent.click(within(d3).getByRole('button', { name: 'ส่งแจ้งเตือน' }))
    await waitFor(() => expect(api.sendReminder).toHaveBeenCalledWith({ customer_uid: 'cu-2', channel: 'LINE', note: expect.any(String) }))
    await waitFor(() => expect(api.reminders).toHaveBeenCalledTimes(2))
    const notices = [...container.querySelectorAll('.notice')].map((n) => n.textContent)
    expect(notices.some((text) => text.includes('อารีย์ พงษ์ไพบูลย์'))).toBe(true)
  })

  // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
  // the second half of Today.test.jsx:473-486 rendered <Today /> → renders
  // <Reminders />. The `offsetsLabel` half stays in Today.test.jsx, where Today.jsx
  // still re-exports the function. The batch left Today (design WP7, F11 a).
  it('heads the reminders with the offsets from meta.offsets', async () => {
    api.reminders.mockResolvedValue({ reminders: [], meta: { total: 0, horizon: '2026-10-30', offsets: [-1, 0] } })
    renderIn('th', <Page />)
    const strip = await screen.findByTestId('reminders')
    await waitFor(() => expect(within(strip).getByTestId('reminder-offsets')).toHaveTextContent('ชุด D-1 / D0'))
    expect(strip).toHaveTextContent('ไม่มีแจ้งเตือนค้างส่งถึง 30/10/2026 (ชุด D-1 / D0 ใน 7 วัน)')
  })

  // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
  // round4.test.jsx:196-203 (J4-21) rendered <Today /> → renders <Reminders />, with
  // round4's own offsets_conflict fixture copied beside it. The batch left Today
  // (design WP7, F11 a). The four assertions are the original, unchanged.
  it('J4-21: draws D-3 against the SOP’s D-1 with the open question named', async () => {
    api.reminders.mockResolvedValue({
      reminders: [],
      meta: {
        total: 0, horizon: '2026-10-30', offsets: [3, 0], batch_label: 'D-3 / D0',
        offsets_conflict: {
          app: '3,0', sop: '1,0', open_question: 'CF1',
          note_th: 'ค่าที่ตั้งไว้ในระบบคือ D-3/D0 แต่ SOP ระบุ D-1/D0 — ข้อขัดแย้ง CF1 ยังไม่มีผู้ตัดสิน',
        },
      },
    })
    renderIn('th', <Page />)
    const conflict = await screen.findByTestId('offsets-conflict')
    expect(conflict).toHaveTextContent('ระบบตั้งไว้ 3,0')
    expect(conflict).toHaveTextContent('SOP ระบุ 1,0')
    expect(conflict).toHaveTextContent('CF1')
    expect(screen.getByTestId('offsets-conflict-note')).toHaveTextContent('ยังไม่มีผู้ตัดสิน')
  })

  it('opens the batch on its own page instead of folding it, under its own title', async () => {
    renderIn('th', <Page />)
    expect(await screen.findByRole('heading', { level: 1, name: 'ชุดแจ้งเตือน' })).toBeInTheDocument()
    expect(await screen.findByTestId('reminders')).toHaveAttribute('open')
  })

  it('a case opened from the batch names this page as the way back', async () => {
    renderIn('th', <Page />)
    const strip = await screen.findByTestId('reminders')
    await waitFor(() => expect(strip.querySelectorAll('[data-reminder]').length).toBe(3))
    fireEvent.click(within(strip.querySelector('[data-reminder="cu-2"]')).getByRole('link'))
    const origin = JSON.parse(window.sessionStorage.getItem('volt.nav.origin'))
    expect(origin).toMatchObject({ for: '/customers/cu-2', path: '/reminders', screenKey: 'today.remindersPage.title' })
  })

  it('a failed batch read says so on the page and never draws an empty batch as "nothing due"', async () => {
    api.reminders.mockRejectedValue(Object.assign(new Error('x'), { problem: { code: 'upstream_down', message_th: 'อ่านชุดแจ้งเตือนไม่ได้' } }))
    renderIn('th', <Page />)
    const strip = await screen.findByTestId('reminders')
    expect(within(strip).getByRole('alert')).toHaveTextContent('อ่านชุดแจ้งเตือนไม่ได้')
    expect(strip).not.toHaveTextContent('ไม่มีแจ้งเตือนค้างส่ง')
  })
})

describe('Today — the batch is no longer on the desk', () => {
  const TODAY = {
    run: { business_date: '2026-10-23' },
    items: [],
    meta: { total: 0, next_up: null, tiers: [], counts_by_tier: {} },
  }

  it('draws no reminder block in list view, never asks for the batch, and links to /reminders', async () => {
    api.today.mockResolvedValue(TODAY)
    renderIn('th', <MemoryRouter initialEntries={['/']}><TodayScreen /></MemoryRouter>)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByTestId('reminders')).toBeNull()
    expect(api.reminders).not.toHaveBeenCalled()
    expect(screen.getByTestId('today-reminders-link')).toHaveAttribute('href', '/reminders')
    expect(screen.getByTestId('today-reminders-link')).toHaveTextContent('ชุดแจ้งเตือน')
  })

  it('draws no reminder block in board view either', async () => {
    window.localStorage.setItem('volt.today.view', 'board')
    api.today.mockResolvedValue(TODAY)
    api.boardColumns = vi.fn().mockResolvedValue({ columns: [] })
    renderIn('th', <MemoryRouter initialEntries={['/']}><TodayScreen /></MemoryRouter>)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByTestId('reminders')).toBeNull()
    expect(screen.getByTestId('today-reminders-link')).toHaveAttribute('href', '/reminders')
    delete api.boardColumns
  })
})
```

`frontend/src/App.reminders.test.jsx` (create — `App.test.jsx`'s own Proxy mock, so every rail fetch resolves):

```jsx
// Feedback Round 1, WP7 / F11 (a): /reminders is a route of its own until the
// calendar (C3). The shape of App.test.jsx's own api mock, so every rail fetch
// resolves.
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from './test-utils.jsx'

vi.mock('./api.js', () => {
  const empty = () => Promise.resolve({
    items: [], rows: [], reviews: [], documents: [], reminders: [], values: [], dictionaries: {},
    run: {}, meta: { total: 0, open: 0, counts_by_tier: {}, tiers: [] },
  })
  const api = new Proxy({}, {
    get(target, prop) {
      if (typeof prop !== 'string') return undefined
      if (!(prop in target)) target[prop] = vi.fn(empty)
      return target[prop]
    },
  })
  return { api, get: vi.fn(empty), post: vi.fn(empty), put: vi.fn(empty), del: vi.fn(empty), CHANGED_EVENT: 'volt:changed' }
})

import App from './App.jsx'

describe('App — /reminders', () => {
  it('routes /reminders to the reminder batch page, not back to Today', async () => {
    window.localStorage.clear()
    renderIn('th', <MemoryRouter initialEntries={['/reminders']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { level: 1, name: 'ชุดแจ้งเตือน' })).toBeInTheDocument()
    expect(await screen.findByTestId('reminders')).toBeInTheDocument()
  })
})
```

`frontend/src/components/Shell.reminders.test.jsx` (create):

```jsx
// Feedback Round 1, WP7 / F11 (a): /reminders has no rail row of its own. With the
// rail closed the trail must still name it — never fall through to the case page's
// "ลูกค้า / สมุดงาน › เคสลูกค้า".
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { renderIn } from '../test-utils.jsx'
import { Shell } from './Shell.jsx'

afterEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe('Shell — the trail on /reminders', () => {
  it('names the reminder batch under งานของฉัน once the rail is closed', () => {
    window.localStorage.setItem('volt.shell.rail', 'closed')
    renderIn('th', <MemoryRouter initialEntries={['/reminders']}><Shell><p>content</p></Shell></MemoryRouter>)
    const nav = document.querySelector('.crumbs')
    expect(nav).not.toBeNull()
    expect(nav.textContent).toContain('งานของฉัน')
    expect(nav.querySelector('.crumbs__current')).toHaveTextContent('ชุดแจ้งเตือน')
    expect(nav.textContent).not.toContain('เคสลูกค้า')
  })
})
```

- [ ] **Step 4: Run them and watch them fail**

Run: `npx vitest run src/screens/Reminders.test.jsx src/App.reminders.test.jsx src/components/Shell.reminders.test.jsx`
Expected: FAIL — `Reminders.test.jsx` cannot resolve `./Reminders.jsx`; the App test finds no heading "ชุดแจ้งเตือน" (the `*` route sends `/reminders` to Today); the Shell test reads `.crumbs__current` "เคสลูกค้า".

- [ ] **Step 5: Implement — the page**

`frontend/src/screens/Reminders.jsx` (create; the block, loader, sender and locals are Today's own, moved — compare with `Today.jsx:123-133`, `:292-300`, `:402-412`, `:503-505`, `:554-563`, `:643-704`):

```jsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api.js'
import { usePrefs, rememberOrigin, clearOrigin } from '../prefs.jsx'
import { fromError } from '../problem.js'
import { formatDate } from '../components/NextAction.jsx'
import { LiveNotice } from '../components/Notice.jsx'
import { Problem } from '../components/Problem.jsx'

// Feedback Round 1, WP7 / F11 (a): the reminder batch left Today — the manager asked
// for the Today list and board without it — and lives here until the calendar (C3)
// takes it in. The block is Today's own, moved: the same endpoint and call
// (`api.reminders({ days: 7 })`), the same test ids, the same Thai. Two things
// changed because this is a page and not a fold on another page — the <details>
// opens by default, and a sent reminder reloads this batch alone (there is no desk
// here to reload) — and one because it was a confident wrong answer: a batch that
// failed to load no longer also says "no reminders due".

// UAT round-2 (N2-13): meta.offsets arrives as [3, 0], [-3, 0] or ['D-3', 'D0'].
// Round-3 N3-05: the number is how many days BEFORE the due date the batch goes
// out, so 3 reads "D-3", never "D+3" — the API's own batch_label says the same and
// is preferred when it is there. Nothing else is computed from it.
export function offsetsLabel(offsets, batchLabel) {
  if (typeof batchLabel === 'string' && batchLabel.trim()) return batchLabel.trim()
  if (!Array.isArray(offsets) || offsets.length === 0) return 'D-3 / D0'
  return offsets.map((o) => {
    if (typeof o === 'string') return o.startsWith('D') ? o : `D${o}`
    const n = Number(o)
    if (!Number.isFinite(n)) return String(o)
    if (n === 0) return 'D0'
    return `D-${Math.abs(n)}`
  }).join(' / ')
}

export default function Reminders() {
  const { t } = usePrefs()
  const location = useLocation()
  const [reminders, setReminders] = useState(null)
  const [problem, setProblem] = useState(null)
  const [flash, setFlash] = useState(null)

  // The reminder batch is its own endpoint (round-1, Nantapol task 8: "I cannot
  // see who gets the next D-3/D0 batch, what the message says, or send one").
  // Round A's lesson: an async answer that lands after the page is gone is dropped.
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  const loadReminders = useCallback(() => {
    api.reminders({ days: 7 })
      .then((d) => { if (alive.current) setReminders(d) })
      .catch((e) => { if (alive.current) setReminders({ reminders: [], meta: {}, problem: fromError(e) }) })
  }, [])
  useEffect(() => { loadReminders() }, [loadReminders])

  // Ruling 56 path 1: a case opened from this page records this page as its origin,
  // so the case page's back control returns here. A return consumes the record, the
  // way Today and the work book consume theirs.
  useEffect(() => {
    if (location.state?.restore) clearOrigin()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key])

  async function sendReminder(r) {
    setProblem(null)
    try {
      await api.sendReminder({ customer_uid: r.customer_uid, channel: 'LINE', note: `${r.kind} reminder sent` })
      if (!alive.current) return
      setFlash(t('today.reminderSent', { name: r.display_name || r.volt_id || r.customer_uid }))
      loadReminders()
    } catch (e) {
      if (alive.current) setProblem(fromError(e))
    }
  }

  const reminderRows = reminders?.reminders || []
  const reminderMeta = reminders?.meta || {}
  const offsets = offsetsLabel(reminderMeta.offsets, reminderMeta.batch_label)
  // The English default note is translated; the API's own Thai wins when present.
  const reminderNote = reminderMeta.note_th
    || (reminderMeta.note && /reminder is a notification/i.test(reminderMeta.note) ? t('today.reminderNoteDefault') : reminderMeta.note)
  // Grouped by due date in the API's order (due date, then name); never re-sorted.
  const reminderDays = []
  for (const r of reminderRows) {
    const last = reminderDays[reminderDays.length - 1]
    if (last && last.due_on === r.due_on) last.rows.push(r)
    else reminderDays.push({ due_on: r.due_on, rows: [r] })
  }

  return (
    <div className="td-page">
      <header className="td-head">
        <div className="td-head__id">
          <h1 className="page-title">{t('today.remindersPage.title')}</h1>
          <p className="page-sub">{t('today.remindersPage.sub')}</p>
        </div>
      </header>
      <LiveNotice tone="quiet" value={flash} onDismiss={() => setFlash(null)} />
      {problem && <Problem problem={problem} />}
      {reminders === null ? (
        <p className="empty">{t('common.loading')}</p>
      ) : (
        <details className="td-reminders" data-testid="reminders" open>
          <summary>
            <span>{t('today.reminders')} · <span data-testid="reminder-offsets" title={t('today.reminderOffsetsHint')}>{t('today.reminderOffsets', { offsets })}</span></span>
            <span className="td-tier__count">{reminderMeta.total ?? reminderRows.length}</span>
          </summary>
          {reminderMeta.template_th && (
            <p className="td-reminders__template" data-testid="reminder-template">{t('today.reminderTemplate')}: {reminderMeta.template_th}</p>
          )}
          {/* A batch that could not be read is said to be unread — never drawn as "no
              reminders due", which would be a confident wrong answer. */}
          {reminders.problem && <Problem problem={reminders.problem} endpoint="/v1/today/reminders" />}
          {reminders.problem ? null : reminderRows.length === 0 ? (
            <p className="td-reminders__empty">
              {reminderMeta.horizon
                ? t('today.remindersNoneUntil', { date: formatDate(reminderMeta.horizon) || reminderMeta.horizon, offsets })
                : t('today.remindersNone')}
            </p>
          ) : (
            <div className="td-reminders__scroll">
              {reminderDays.map((day) => (
                <div key={day.due_on || 'none'} data-reminder-day={day.due_on}>
                  <p className="td-reminders__day">{t('today.dueOn', { date: formatDate(day.due_on) || day.due_on || '—' })}</p>
                  {day.rows.map((r) => (
                    <div className="td-reminders__row" key={`${r.customer_uid}-${r.due_on}`} data-reminder={r.customer_uid}>
                      <Link
                        className="td-name"
                        to={`/customers/${r.customer_uid}`}
                        onClick={() => rememberOrigin({
                          for: `/customers/${r.customer_uid}`, path: '/reminders', search: window.location.search,
                          screenKey: 'today.remindersPage.title', filtered: false, restore: null, scrollY: window.scrollY,
                        })}
                      >{r.display_name || r.volt_id || r.customer_uid}</Link>
                      <span className="td-quiet">{t(`today.reminder.${r.kind}`) === `today.reminder.${r.kind}` ? r.kind : t(`today.reminder.${r.kind}`)}</span>
                      {r.overdue && <span className="td-overdue">{t('today.reminderOverdue')}</span>}
                      <span className="td-quiet">{r.officer_uid}</span>
                      <button type="button" className="btn btn--sm" onClick={() => sendReminder(r)}>{t('today.reminderSend')}</button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
          {reminderNote && <p className="td-reminders__note" data-testid="reminder-note">{reminderNote}</p>}
          {/* Round-4 J4-21c: the API has said all round that its own D-3/D0 disagrees
              with the SOP's D-1/D0 and that CF1 is unowned — and no screen read the
              field. The officer sending a batch sees the disagreement on the card. */}
          {reminderMeta.offsets_conflict && (
            <p className="td-reminders__conflict" data-testid="offsets-conflict">
              <strong>{t('today.offsetsConflictLabel')}</strong>
              {' · '}{t('today.offsetsConflictPair', {
                app: reminderMeta.offsets_conflict.app || offsets,
                sop: reminderMeta.offsets_conflict.sop || '—',
              })}
              {reminderMeta.offsets_conflict.open_question && (
                <> · {t('today.offsetsConflictOpen', { code: reminderMeta.offsets_conflict.open_question })}</>
              )}
              {reminderMeta.offsets_conflict.note_th && (
                <span className="td-quiet" data-testid="offsets-conflict-note"> {reminderMeta.offsets_conflict.note_th}</span>
              )}
            </p>
          )}
        </details>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Implement — Today loses the block and gains the link**

`frontend/src/screens/Today.jsx`, in this order (every anchor is HEAD text):

1. Replace the four comment lines `:29-32` (from `// UAT round-2 (N2-13): meta.offsets arrives as [3, 0], [-3, 0] or ['D-3', 'D0'].` through `// is preferred when it is there. Nothing else is computed from it.`) with:
   ```jsx
   // Feedback Round 1, WP7 / F11: the D-3/D0 reminder batch left this screen for
   // /reminders (screens/Reminders.jsx); `offsetsLabel` moved with it and is
   // re-exported below so existing imports of it keep working.
   ```
2. Replace the whole `export function offsetsLabel(offsets, batchLabel) { … }` at `:123-133` with the one line:
   ```jsx
   export { offsetsLabel } from './Reminders.jsx'
   ```
3. Delete `:164`: `  const [reminders, setReminders] = useState(null)`.
4. Delete `:292-300` plus the blank line after it — from `  // The reminder batch is its own endpoint (round-1, Nantapol task 8: "I cannot` through `  useEffect(() => { loadReminders() }, [loadReminders])`.
5. Delete `:402-412` plus the blank line after it — the whole `  async function sendReminder(r) { … }`.
6. Delete `:503-505`:
   ```jsx
     const reminderRows = reminders?.reminders || []
     const reminderMeta = reminders?.meta || {}
     const offsets = offsetsLabel(reminderMeta.offsets, reminderMeta.batch_label)
   ```
7. Delete `:554-563` — from `  // The English default note is translated; the API's own Thai wins when present.` through the `  }` that closes the `for (const r of reminderRows)` loop.
8. Delete `:643-704` plus the blank line after it — from `  const remindersBlock = (` through its closing `  )`, the line before the blank line above `  const workloadBlock =`.
9. In the list view (`:971-973`) and the board view (`:1142-1144`), delete the line `          {remindersBlock}` (both occurrences).
10. In `.td-head__controls`, replace `:817`
    ```jsx
              <button type="button" className="btn btn--sm" onClick={load}>{t('common.refresh')}</button>
    ```
    with
    ```jsx
              {/* Feedback Round 1, WP7 / F11: the reminder batch has its own page until the
                  calendar takes it in; this is the one way to it from the desk. */}
              <Link className="btn btn--sm" to="/reminders" data-testid="today-reminders-link">{t('today.remindersLink')}</Link>
              <button type="button" className="btn btn--sm" onClick={load}>{t('common.refresh')}</button>
    ```

Then `grep -n "remindersBlock\|loadReminders\|sendReminder\|reminderMeta\|reminderRows\|setReminders\|reminderDays" src/screens/Today.jsx` must print nothing. (`td-reminders` stays on the workload fold's classes until B2b removes that fold.)

`frontend/src/App.jsx`: after `:6` `import Today from './screens/Today.jsx'` add `import Reminders from './screens/Reminders.jsx'`; after `:104` `        <Route path="/" element={<Today />} />` add:

```jsx
        {/* Feedback Round 1, WP7 / F11: the reminder batch, off Today, until C3's calendar. */}
        <Route path="/reminders" element={<Reminders />} />
```

`frontend/src/components/Shell.jsx`: replace `:81-84`

```jsx
const RAIL_ALIASES = { '/customers': '/workbook' }

function findActiveRail(pathname) {
  const target = RAIL_ALIASES[pathname] || pathname
```

with

```jsx
const RAIL_ALIASES = { '/customers': '/workbook' }

// Feedback Round 1, WP7 / F11: a page with no rail row of its own, reached from a
// rail screen. Named here so the trail reads "งานของฉัน › ชุดแจ้งเตือน" instead of
// falling through to the case page's crumbs. /reminders leaves with C3's calendar.
const SUB_PAGES = { '/reminders': { group: 'nav.myWork', label: 'today.remindersPage.title' } }

function findActiveRail(pathname) {
  const sub = SUB_PAGES[pathname]
  if (sub) return { group: { label: sub.group }, item: { label: sub.label } }
  const target = RAIL_ALIASES[pathname] || pathname
```

`frontend/src/i18n-today.js`: after `:164` `  'today.reminders': 'Reminders to send today',` add

```js
  // Feedback Round 1, WP7 / F11: the batch has its own page until the calendar.
  'today.remindersLink': 'Reminder batch',
  'today.remindersPage.title': 'Reminder batch',
  'today.remindersPage.sub': 'Who gets the next D-3 / D0 reminder, what the message says, and a send button for each — a reminder is a notification, not a collection contact.',
```

and after `:753` `  'today.reminders': 'แจ้งเตือนที่ต้องส่งวันนี้',` add

```js
  // Feedback Round 1, WP7 / F11: หน้าแยกของชุดแจ้งเตือน จนกว่าปฏิทินจะรับไป
  'today.remindersLink': 'ชุดแจ้งเตือน',
  'today.remindersPage.title': 'ชุดแจ้งเตือน',
  'today.remindersPage.sub': 'ใครจะได้รับแจ้งเตือน D-3 / D0 รอบถัดไป ข้อความว่าอย่างไร และปุ่มส่งของแต่ละราย — แจ้งเตือนเป็นการแจ้งข้อมูล ไม่ใช่การติดต่อทวงถาม',
```

(The existing `today.reminder*` keys stay; the page still uses them.)

- [ ] **Step 7: Spend edit 36 — the three pinned batch tests leave Today's files**

`frontend/src/screens/Today.test.jsx`: delete `:272-304` (the whole `it('shows the next seven days of reminders grouped by due date, with the template, and marks one sent', …)` block, up to the blank line before `it('opens the contact drawer from a row'`) and put in its place:

```jsx
  // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
  // "shows the next seven days of reminders…" rendered <Today /> → moved to
  // screens/Reminders.test.jsx, rendering <Reminders />. The batch left Today for
  // /reminders (design WP7, F11 a); its assertions moved with it unchanged except the
  // hero wait and the second /v1/today call, which that page does not have.

```

In the same file replace `:480-486`

```jsx
    expect(offsetsLabel([3, 0], 'D-3 / D0')).toBe('D-3 / D0')
    api.reminders.mockResolvedValue({ reminders: [], meta: { total: 0, horizon: '2026-10-30', offsets: [-1, 0] } })
    renderIn('th', <Today />)
    const strip = await screen.findByTestId('reminders')
    await waitFor(() => expect(within(strip).getByTestId('reminder-offsets')).toHaveTextContent('ชุด D-1 / D0'))
    expect(strip).toHaveTextContent('ไม่มีแจ้งเตือนค้างส่งถึง 30/10/2026 (ชุด D-1 / D0 ใน 7 วัน)')
  })
```

with

```jsx
    expect(offsetsLabel([3, 0], 'D-3 / D0')).toBe('D-3 / D0')
    // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
    // the four lines that rendered <Today /> and read the batch's heading → moved to
    // screens/Reminders.test.jsx ("heads the reminders with the offsets from
    // meta.offsets"), rendering <Reminders />. The batch left Today (design WP7, F11 a).
  })
```

`frontend/src/round4.test.jsx`: replace `:196-203` (the first `it` inside `describe('J4-21 — offsets_conflict, …')`; the second, `sends a reminder from the case…`, stays) with:

```jsx
  // AUTHORISED TEST EDIT 36 (Feedback Round 1 plan, Arina's approval 2026-09-15):
  // "draws D-3 against the SOP’s D-1…" rendered <Today /> → moved to
  // screens/Reminders.test.jsx (J4-21), rendering <Reminders /> with this file's
  // offsets_conflict fixture. The batch left Today (design WP7, F11 a); the four
  // assertions moved unchanged.
```

- [ ] **Step 8: Run the focused tests, the suite and the census**

Run: `npx vitest run src/screens/Reminders.test.jsx src/App.reminders.test.jsx src/components/Shell.reminders.test.jsx src/screens/Today.test.jsx src/round4.test.jsx src/screens/Today.board.test.jsx src/api.test.js src/i18n.test.js src/components/Shell.test.jsx src/components/Shell.rail.test.jsx src/App.test.jsx`
Expected (measured on a scratch copy): 12 files, 153 tests, all PASS. `Reminders.test.jsx` 8, `Today.test.jsx` 31 (was 32), `round4.test.jsx` 44 (was 45).

Run: `npx vitest run 2>&1 | tail -4`
Expected: PASS at Step 1's baseline **+ 3 files, + 8 tests** (+10 added, −2 moved out). Paste the count.

Run: `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected (measured): `TODAY  chrome=108  perRow=31  at 50 rows=1658 …` and `TODAY  full page (50 rows) visible=1658`. Paste both lines.

- [ ] **Step 9: Commit**

```bash
MSG=$(mktemp)
cat > "$MSG" <<'EOF'
feat(today): the reminder batch leaves Today for its own page, /reminders

Design WP7 / F11 (a). The same block, endpoint and test ids on /reminders until the
calendar takes it in; Today keeps one link to it. The trail names the page when the
rail is closed. A failed batch read no longer also says "no reminders due".

AUTHORISED TEST EDIT 36: three pinned tests that read the batch on Today moved to
Reminders.test.jsx (Today.test.jsx:272-304 and :481-485, round4.test.jsx:196-203).
Today density: chrome 112 -> 108, per row 31, page 1,662 -> 1,658.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/screens/Reminders.jsx frontend/src/screens/Reminders.test.jsx frontend/src/App.reminders.test.jsx frontend/src/components/Shell.reminders.test.jsx
git commit -F "$MSG" -- frontend/src/screens/Reminders.jsx frontend/src/screens/Reminders.test.jsx frontend/src/App.reminders.test.jsx frontend/src/components/Shell.reminders.test.jsx frontend/src/screens/Today.jsx frontend/src/App.jsx frontend/src/components/Shell.jsx frontend/src/i18n-today.js frontend/src/screens/Today.test.jsx frontend/src/round4.test.jsx
```

---

### Task B3: One folded "หมายเหตุระบบ (n)" on Today, Recovery and InvoicePipeline

**Files:**
- Create: `frontend/src/components/SystemNotes.jsx`, `frontend/src/components/SystemNotes.test.jsx`, `frontend/src/screens/Today.notes.test.jsx`
- Modify: `frontend/src/screens/Today.jsx` (HEAD `:15`, `:568-582`, `:747`, `:786-795`, `:821-832`, `:974-1001`, `:1121`, `:1151-1160`; B1 has already removed the reminder lines between them)
- Modify: `frontend/src/screens/Recovery.jsx:7`, `:281-285`, `:353`, `:460-461`
- Modify: `frontend/src/screens/InvoicePipeline.jsx:12`, `:582-584`
- Modify: `frontend/src/realign.css` after `:187`
- Modify: `frontend/src/i18n-journey.js` after `:387` (EN) and `:821` (TH)
- Test (append only): `frontend/src/screens/Recovery.test.jsx`, `frontend/src/screens/InvoicePipeline.test.jsx`

**Interfaces:**
- Consumes: nothing served; the notes are the blocks Today, Recovery and InvoicePipeline already render.
- Produces:
  - `export function SystemNotes({ children, testid = 'system-notes' })` — a native `<details className="sysnotes" data-testid={testid}>`, shut by default, with `<summary className="sysnotes__summary">` reading `t('sysnotes.summary', { n })` where `n = Children.toArray(children).length` (false/null children are not notes), and `<div className="sysnotes__body">` holding every note, always rendered. Renders nothing when `n === 0`.
  - i18n key (i18n-journey.js, both tables, a component key like `filter.*`): `sysnotes.summary` — EN `System notes ({n})`, TH `หมายเหตุระบบ ({n})`.
  - Today, inside the fold (all test ids and ids unchanged): `pick-officer`, `refusal-od04` (`id="td-od04-refusal"`), `refusal-cf1` (`id="td-cf1-refusal"`), `dial-disabled-why` with `dial-off-phone` / `dial-off-line` (list view), `ptp-history-note` (list view), `board-rule-note` and `board-seeding-note` (board view), `count-note`, `counts-note-api`. The fold sits right after `</header>`, before the `LiveNotice`. The header's "ทำไมตัวเลขแต่ละที่ไม่เท่ากัน" fold is gone (its two notes are in this one).
  - Recovery, inside the fold (per tab): `rec-note-cash-rule` (npl and cash tabs), `rec-note-fee` (recovery tab), `rec-note-cash-path` (cash tab). InvoicePipeline: its `pipe.owner` `<Notice>` (keeps `role="status"`).

**Pins:** 0, measured — `InvoicePipeline.test.jsx:102` (`getByRole('status')` finds the notice inside the shut `<details>`: jsdom gives it `display: block`; a probe with `hidden` instead returned 0 matches, which is why the fold must never use `hidden`); `Recovery.test.jsx:175` (entry gate stays in `restructure-figures`), `:186`, `:188` (exactly one cash rule per tab); `Today.test.jsx:390-400`, `:446`, `:520`, `:591-596`, `:611-676`; every `Today.board.test.jsx` test. Density: chrome 108 → **105**, row 31, page 1,658 → **1,655** (measured: dial line −3, header fold −2, new fold +2).

- [ ] **Step 1: Re-measure**

Run: `git log --oneline -3 && git status --short`, `npx vitest run 2>&1 | tail -4`, `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected: B1's count; `chrome=108  perRow=31  at 50 rows=1658`.

- [ ] **Step 2: Grep the key and the ids**

Run: `grep -n "sysnotes\|system-notes\|rec-note-" src/i18n-*.js src/*.css src/screens/*.jsx src/components/*.jsx`
Expected: no output.

- [ ] **Step 3: Write the failing tests**

`frontend/src/components/SystemNotes.test.jsx` (create):

```jsx
// Feedback Round 1, WP7 / F10 (a): one folded "หมายเหตุระบบ (n)" per screen, and
// everything inside it stays reachable while it is shut.
import { describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'
import { SystemNotes } from './SystemNotes.jsx'

describe('SystemNotes', () => {
  it('draws nothing at all when there is no note to fold', () => {
    const { container } = renderIn('th', <SystemNotes>{false}{null}</SystemNotes>)
    expect(container.querySelector('details')).toBeNull()
  })

  it('counts only the notes actually shown, in Thai and in English', () => {
    const first = renderIn('th', (
      <SystemNotes>
        <p>หนึ่ง</p>
        {false}
        <p>สอง</p>
      </SystemNotes>
    ))
    expect(screen.getByTestId('system-notes').querySelector('summary')).toHaveTextContent('หมายเหตุระบบ (2)')
    first.unmount()
    renderIn('en', <SystemNotes><p>one</p></SystemNotes>)
    expect(screen.getByTestId('system-notes').querySelector('summary')).toHaveTextContent('System notes (1)')
  })

  it('is shut by default, yet every note, its id and its role stay in the document', () => {
    renderIn('th', (
      <SystemNotes>
        <p id="td-od04-refusal" data-testid="refusal-od04">band</p>
        <div role="status">owner</div>
      </SystemNotes>
    ))
    const fold = screen.getByTestId('system-notes')
    expect(fold.tagName).toBe('DETAILS')
    expect(fold).not.toHaveAttribute('open')
    expect(screen.getByTestId('refusal-od04')).toHaveAttribute('id', 'td-od04-refusal')
    expect(fold).toContainElement(screen.getByRole('status'))
    expect(fold.querySelector('[hidden]')).toBeNull()
    fireEvent.click(fold.querySelector('summary'))
    expect(screen.getByTestId('refusal-od04')).toBeInTheDocument()
  })
})
```

`frontend/src/screens/Today.notes.test.jsx` (create):

```jsx
// Feedback Round 1, WP7 / F10 (a): Today's standing notices fold into ONE
// "หมายเหตุระบบ (n)" at the end of the header, in list view and board view. Nothing
// is deleted: every note keeps its test id and its id, inside the shut fold.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setOfficer, setRole } from '../components/role.jsx'
import TodayScreen from './Today.jsx'

vi.mock('../api.js', () => ({
  api: {
    today: vi.fn(), todayItemDone: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(), dictionary: vi.fn(),
    logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(), boardColumns: vi.fn(), boardMove: vi.fn(),
  },
}))

const TIERS = ['PTP_DUE_TODAY', 'NEXT_ACTION_DUE', 'BROKEN_PTP', 'AT_RISK_TWO_MISSED',
               'NEW_ARREARS', 'ANSWER_WAITING', 'ROUTINE']

const LADDER_AHEAD = {
  kind: 'CASH', source: 'CASH_LADDER', mode: 'ASSISTED', stage: 'NORMAL', indicative: 'SETTLEMENT_PLAN_60',
  pending_decision: 'OD-04', note: 'x',
  steps: [
    { stage: 'NOTICE_30', day: 30, act: 'notice', act_th: 'แจ้งเตือนและให้เวลาชำระ' },
    { stage: 'SETTLEMENT_PLAN_60', day: 60, act: 'plan', act_th: 'เสนอแผนผ่อนชำระยอดคงค้าง' },
  ],
}

const ITEM = (uid, over = {}) => ({
  customer: { uid, customer_no: `C-${uid}`, display_name: `ลูกค้า ${uid}`, phone_masked: '08x-xxx-0000',
              phone_e164: null, line_id: null, contract_count: 1, officer: 'nantapol' },
  entity: 'SPV', company_id: 'CO-SPV', aggregate_overdue: '2999.00', aggregate_outstanding: '212928.99',
  oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL',
  contact_lock: { state: 'OPEN' }, ladder: LADDER_AHEAD, waiting: [], missed_count: 1,
  tier: 'NEXT_ACTION_DUE', tier_rank: 2, board_column_id: 'col-1',
  money_position: { amount_to_ask: '2999.00', penalty_invoicing_enabled: false, penalty_rule_owner: 'OD-31', note_th: 'x' },
  case: { uid: `case-${uid}`, payment_status: 'LATE', dc_status: 'NO_ACTION', next_action: 'CALL',
          next_action_on: '2026-10-23', kept_ptp_count: 0, broken_ptp_count: 1, open_ptp: null, officer_uid: 'nantapol' },
  ...over,
})

const RESPONSE = {
  run: { business_date: '2026-10-23' },
  items: [ITEM('cu-1'), ITEM('cu-2')],
  meta: {
    total: 2, next_up: 'cu-1', tiers: TIERS,
    counts_by_tier: { NEXT_ACTION_DUE: 2 },
    counts_note_th: 'ชิปแต่ละขั้นรวมกันได้เท่ากับจำนวนรายการทั้งหมด',
    ptp_history_note_th: 'ยังไม่มีนัดที่บันทึกว่าชำระตามนัดในระบบ',
  },
}

const Today = ({ entry = '/' } = {}) => <MemoryRouter initialEntries={[entry]}><TodayScreen /></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  setRole('OFFICER')
  setOfficer('nantapol')
  api.today.mockResolvedValue(RESPONSE)
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  api.boardColumns.mockResolvedValue({ columns: [{ column_id: 'col-1', name: 'Call today', order: 1 }] })
})

describe('Today — หมายเหตุระบบ (F10)', () => {
  it('folds the list view’s standing notices into one shut line that counts them', async () => {
    renderIn('th', <Today />)
    const fold = await screen.findByTestId('system-notes')
    expect(fold.tagName).toBe('DETAILS')
    expect(fold).not.toHaveAttribute('open')
    // OD-04 band, CF1 band, dial-off, PTP history, count note, the API's count note.
    expect(fold.querySelector('summary')).toHaveTextContent('หมายเหตุระบบ (6)')
    for (const id of ['refusal-od04', 'refusal-cf1', 'dial-disabled-why', 'ptp-history-note', 'count-note', 'counts-note-api']) {
      expect(fold, id).toContainElement(screen.getByTestId(id))
    }
    // Exactly one fold on the screen, and none of the notes also sits on the face.
    expect(screen.getAllByTestId('system-notes')).toHaveLength(1)
    expect(screen.getAllByTestId('refusal-od04')).toHaveLength(1)
  })

  it('the column marks still point at the folded bands by id', async () => {
    const { container } = renderIn('th', <Today />)
    await screen.findByTestId('system-notes')
    const group = container.querySelector('#td-tier-NEXT_ACTION_DUE')
    const dpd = within(group).getAllByRole('columnheader').find((th) => th.textContent.includes('DPD'))
    expect(dpd).toHaveAttribute('aria-describedby', 'td-od04-refusal')
    expect(screen.getByTestId('system-notes')).toContainElement(document.getElementById('td-od04-refusal'))
    expect(screen.getByTestId('system-notes')).toContainElement(document.getElementById('td-cf1-refusal'))
  })

  it('the fold sits between the header and the work, not at the bottom of the page', async () => {
    const { container } = renderIn('th', <Today />)
    const fold = await screen.findByTestId('system-notes')
    const head = container.querySelector('.td-head')
    const hero = await screen.findByRole('region', { name: 'รายต่อไป' })
    expect(head.compareDocumentPosition(fold) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(fold.compareDocumentPosition(hero) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('the pick-your-name line folds too, and its button still reaches the officer control', async () => {
    renderIn('th', <Today entry="/?officer=" />)
    const fold = await screen.findByTestId('system-notes')
    const pick = screen.getByTestId('pick-officer')
    expect(fold).toContainElement(pick)
    fireEvent.click(fold.querySelector('summary'))
    fireEvent.click(within(pick).getByRole('button'))
    expect(document.activeElement).toBe(screen.getByLabelText('แสดงงานของ'))
  })

  it('board view folds what ย้าย… does and why a card sits in its column, and draws no dial line', async () => {
    window.localStorage.setItem('volt.today.view', 'board')
    renderIn('th', <Today />)
    await screen.findByTestId('board')
    const fold = screen.getByTestId('system-notes')
    expect(fold).toContainElement(screen.getByTestId('board-rule-note'))
    expect(fold).toContainElement(screen.getByTestId('board-seeding-note'))
    expect(screen.getByTestId('board-seeding-note')).toHaveTextContent('ทำไมการ์ดนี้อยู่คอลัมน์นี้')
    expect(fold).toContainElement(screen.getByTestId('refusal-od04'))
    expect(screen.queryByTestId('dial-disabled-why')).toBeNull()
    expect(document.querySelectorAll('details.page-note')).toHaveLength(0)
  })
})
```

Append to the end of `frontend/src/screens/Recovery.test.jsx` (its own `mocks`, `renderIn`, `MemoryRouter`, `fireEvent` are already imported at `:1-4`):

```jsx

// Feedback Round 1, WP7 / F10 (a): the tab's standing rules fold into one
// "หมายเหตุระบบ (n)" under the tabs. Added tests; nothing above is edited.
describe('Recovery — หมายเหตุระบบ (F10)', () => {
  it('folds each tab’s standing rules into one shut line, and the case cards keep their own facts', async () => {
    renderIn('en', <MemoryRouter><Recovery /></MemoryRouter>)
    await screen.findByTestId('npl-npl-0011')
    const fold = screen.getByTestId('system-notes')
    expect(fold).not.toHaveAttribute('open')
    expect(fold.querySelector('summary')).toHaveTextContent('System notes (1)')
    expect(fold).toContainElement(screen.getByText(/No restructure and no NPL for cash/))
    fireEvent.click(screen.getByTestId('rec-tab-recovery'))
    expect(screen.getByTestId('system-notes')).toContainElement(screen.getByTestId('rec-note-fee'))
    expect(screen.queryByText(/No restructure and no NPL for cash/)).toBeNull()
    fireEvent.click(screen.getByTestId('rec-tab-cash'))
    const cashFold = screen.getByTestId('system-notes')
    expect(cashFold.querySelector('summary')).toHaveTextContent('System notes (2)')
    expect(cashFold).toContainElement(screen.getByTestId('rec-note-cash-rule'))
    expect(cashFold).toContainElement(screen.getByTestId('rec-note-cash-path'))
    expect(screen.getAllByTestId('system-notes')).toHaveLength(1)
  })
})
```

Append to the end of `frontend/src/screens/InvoicePipeline.test.jsx` (uses its own `show()` at `:52`):

```jsx

// Feedback Round 1, WP7 / F10 (a): the owner notice folds into "หมายเหตุระบบ (1)" and
// keeps its role="status" inside. Added test; nothing above is edited.
describe('InvoicePipeline — หมายเหตุระบบ (F10)', () => {
  it('folds the invoice-owner notice, shut, with its status role intact', async () => {
    await show()
    const fold = screen.getByTestId('system-notes')
    expect(fold).not.toHaveAttribute('open')
    expect(fold.querySelector('summary')).toHaveTextContent('System notes (1)')
    expect(fold).toContainElement(screen.getByRole('status'))
  })
})
```

- [ ] **Step 4: Run them and watch them fail**

Run: `npx vitest run src/components/SystemNotes.test.jsx src/screens/Today.notes.test.jsx src/screens/Recovery.test.jsx src/screens/InvoicePipeline.test.jsx`
Expected: FAIL — `SystemNotes.test.jsx` cannot resolve `./SystemNotes.jsx`; the Today, Recovery and InvoicePipeline additions time out on / cannot find `system-notes`. Every pre-existing test in the two appended files still passes.

- [ ] **Step 5: Implement — the component, its style, its key**

`frontend/src/components/SystemNotes.jsx` (create):

```jsx
import { Children } from 'react'
import { useT } from '../prefs.jsx'

// Feedback Round 1, WP7 / design F10 (a): "remove the messy notices on every screen".
// The standing notices — the ones that say the same thing whatever the officer does
// next (a refusal band, why a button is off, where a count comes from) — fold into ONE
// line per screen, "หมายเหตุระบบ (n)", closed by default.
//
// Deliberate refusals stay refused (design contract §3): nothing is deleted, only
// folded. So the fold is a native <details> and every note is ALWAYS rendered inside
// it — never mounted on open, never `hidden`. That keeps every note's id (the column
// heads' aria-describedby point at two of them) and every test id reachable while the
// fold is shut, and it keeps a `role="status"` note (InvoicePipeline.test.jsx:102)
// findable by role.
//
// `n` is how many notes this screen is showing right now — a count of elements on
// the page, not a figure the server owns. A false/null child is not a note.
export function SystemNotes({ children, testid = 'system-notes' }) {
  const t = useT()
  const notes = Children.toArray(children)
  if (notes.length === 0) return null
  return (
    <details className="sysnotes" data-testid={testid}>
      <summary className="sysnotes__summary">{t('sysnotes.summary', { n: notes.length })}</summary>
      <div className="sysnotes__body">{notes}</div>
    </details>
  )
}
```

`frontend/src/realign.css`, after `:186-187` (`.undecided-mark { … text-underline-offset: 3px; }`):

```css
/* Feedback Round 1, WP7 / F10 (a): the one folded "หมายเหตุระบบ (n)" per screen
   (components/SystemNotes.jsx). Shut, it is one quiet caption line — the same weight
   as Today's old "why these counts differ" footnote it absorbed; open, each note
   keeps its own class (a violet refusal band stays violet). Tokens only. */
.sysnotes { margin: 0; }
.sysnotes__summary {
  display: inline-block; cursor: pointer; list-style: none;
  font: var(--caption-12); color: var(--ink-600);
  border-bottom: 1px dashed var(--line-default); padding-bottom: 1px;
}
.sysnotes__summary::-webkit-details-marker { display: none; }
.sysnotes__summary::before { content: '+ '; }
.sysnotes[open] .sysnotes__summary::before { content: '– '; }
.sysnotes__summary:hover { color: var(--ink-800); }
.sysnotes__summary:focus-visible { outline: 2px solid var(--ink-900); outline-offset: 2px; }
.sysnotes__body { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; max-width: 92ch; }
.sysnotes__body > p { margin: 0; }
```

`frontend/src/i18n-journey.js`: after `:387` `  'filter.none': 'No match',` add

```js
  // Feedback Round 1, WP7 / F10: the one folded line of standing notices per screen.
  'sysnotes.summary': 'System notes ({n})',
```

after `:821` `  'filter.none': 'ไม่พบรายการที่ตรงกัน',` add

```js
  // Feedback Round 1, WP7 / F10: บรรทัดพับหมายเหตุระบบ หนึ่งบรรทัดต่อหน้าจอ
  'sysnotes.summary': 'หมายเหตุระบบ ({n})',
```

- [ ] **Step 6: Implement — Today folds its notices**

`frontend/src/screens/Today.jsx` (anchors are HEAD text; B1 has removed the reminder lines around them):

1. After `:15` `import { Notice, PendingBadge, LiveNotice } from '../components/Notice.jsx'` add `import { SystemNotes } from '../components/SystemNotes.jsx'`.
2. Replace the comment paragraph `:568-582` (from `  // Reading-order §4.3: both bands now sit BELOW the work object (the hero in` through `  // resolves by id, not DOM order, so the association survives the move.`) with:
   ```jsx
     // Feedback Round 1, F10: both bands now live in the one "หมายเหตุระบบ" fold
     // (`systemNotes`, below). Ruling 60 specifies each band's Thai, binding and <th>
     // mark and states no position; the marks resolve by id, so they survive the fold.
   ```
3. Immediately before `  return (` (HEAD `:747`, the line after `workloadBlock`'s closing `  )` and its blank line) insert:
   ```jsx
     // Feedback Round 1, WP7 / design F10 (a): every standing notice on this desk folds
     // into ONE "หมายเหตุระบบ (n)" at the end of the header. Nothing is deleted — the
     // design contract's deliberate refusals stay refused — and nothing is mounted on
     // open (SystemNotes.jsx): the two bands keep their ids, so every column head's
     // aria-describedby still resolves (by id, not by DOM position), and every test id
     // stays reachable while the fold is shut. The hero's own short CF1 clause and its
     // OD-04 PendingBadge stay on the face, so neither refusal leaves the face entirely.
     // Order: who the desk is for, what nobody has decided, why a control is off, where
     // a number comes from.
     const systemNotes = (
       <SystemNotes>
         {/* Round-2 J-10: an OFFICER with no officer chosen sees the whole book; the
             button lands focus on the officer control. */}
         {role === 'OFFICER' && !officer && (
           <p className="td-pick" data-testid="pick-officer">
             <span>{t('today.pickOfficer')}</span>
             <button type="button" className="btn btn--sm" onClick={() => officerSelect.current && officerSelect.current.focus()}>
               {t('today.pickOfficerGo')}
             </button>
           </p>
         )}
         {od04Block}
         {cf1Block}
         {/* R1-C05 / J3-14: why โทร and LINE are off, once for the list, with how many rows
             it covers. List view only (ruling 50: the board draws no dial control). */}
         {view === 'list' && (noPhoneRows > 0 || noLineRows > 0) && (
           <p className="td-dial-why" data-testid="dial-disabled-why">
             {noPhoneRows > 0 && <span data-testid="dial-off-phone">{t('today.dialOffPhone', { n: noPhoneRows })}</span>}
             {noPhoneRows > 0 && noLineRows > 0 && ' · '}
             {noLineRows > 0 && <span data-testid="dial-off-line">{t('today.dialOffLine', { n: noLineRows })}</span>}
           </p>
         )}
         {/* F1 (ruling 59): served once per desk; absent key -> nothing. */}
         {view === 'list' && meta.ptp_history_note_th && (
           <p className="td-dial-why" data-testid="ptp-history-note">{meta.ptp_history_note_th}</p>
         )}
         {/* Ruling 50 (B2 §1) and R-CAP-2: what ย้าย… does, and why a card sits where it does. */}
         {view === 'board' && (
           <p className="td-dial-why" data-testid="board-rule-note">{t('today.board.whatDragDoes')}</p>
         )}
         {view === 'board' && (
           <p className="td-quiet" data-testid="board-seeding-note">
             <strong>{t('today.board.seedingSummary')}</strong> {t('today.board.seedingNote')}
           </p>
         )}
         {/* The badge, this header and the work book count different things; said once. */}
         <p className="td-quiet" data-testid="count-note">{t('today.countNote')}</p>
         {meta.counts_note_th && <p className="td-quiet" data-testid="counts-note-api">{meta.counts_note_th}</p>}
       </SystemNotes>
     )

   ```
4. Delete the header fold `:786-795` — from `          {/* Two reconciliation notes used to sit open under the title, three lines` through `          </details>` (the `page-note` details holding `count-note` and `counts-note-api`).
5. Replace the pick-officer block `:821-832` (from `      {/* An OFFICER with no officer chosen sees the whole book (round-2, J-10): say` through its closing `      )}`) with the one line `      {systemNotes}` — so it sits directly above `      <LiveNotice tone="quiet" value={flash} …`.
6. List view: delete `          {od04Block}` and `          {cf1Block}` (`:974-975`), and delete `:977-1001` — the R1-C05 comment and `dial-disabled-why` paragraph, the F1 comment and `ptp-history-note` paragraph — up to the blank line before `          {tiers.map((tier) => {`. The list view then reads, exactly: `          )}`, a blank line, `          {tiersBlock}`, `          {workloadBlock}`, a blank line, `          {tiers.map((tier) => {` (B2b's patch matches these lines).
7. Board view: replace `:1112-1121` — the nine-line comment that starts `          {/* Ruling 50 (B2 §1): the board is the first CONTENT block — the drag-note` and the `board-rule-note` paragraph under it — with:
   ```jsx
             {/* Ruling 50 (B2 §1): the board is the first CONTENT block. Feedback Round 1,
                 F10: the drag-note caption and both bands now sit in the หมายเหตุระบบ fold
                 under the header; each column head still carries its own aria-describedby,
                 computed below, which is what qualifies the money/DPD figures on a card. */}
   ```
8. Board view: delete `:1145-1160` — the Reading-order §4.3 comment, `          {od04Block}`, `          {cf1Block}`, the R-CAP-2 comment and the `page-note` details holding `board-seeding-note` — leaving `          {tiersBlock}` and `          {workloadBlock}` as the last children before `        </>`.

Check: `grep -n "page-note\|{od04Block}\|{cf1Block}\|data-testid=\"dial-disabled-why\"\|data-testid=\"board-rule-note\"" src/screens/Today.jsx` prints exactly one line each for `{od04Block}`, `{cf1Block}`, `dial-disabled-why` and `board-rule-note` — all inside `systemNotes` — and no `page-note`.

- [ ] **Step 7: Implement — Recovery and InvoicePipeline**

`frontend/src/screens/Recovery.jsx`: after `:7` add `import { SystemNotes } from '../components/SystemNotes.jsx'`. Replace `:281-285`

```jsx
      <LiveNotice tone="info" value={note} onDismiss={() => setNote(null)} />

      {tab === 'npl' && (
        <div role="tabpanel" id="rec-panel-npl" aria-labelledby="rec-tab-npl" className="ad-section">
          <Notice tone="quiet">{t('rec.cashRule')}</Notice>
```

with

```jsx
      {/* Feedback Round 1, WP7 / F10 (a): the tab's standing rules fold into one
          "หมายเหตุระบบ (n)" under the tabs — the same rules, one click down. What stays
          on a card is a fact about THAT case (an outcome, a buyback figure, a deed not
          yet executed, the restructure entry gate beside its four figures), not a
          standing notice. */}
      <SystemNotes>
        {(tab === 'npl' || tab === 'cash') && <p className="ad-quiet" data-testid="rec-note-cash-rule">{t('rec.cashRule')}</p>}
        {tab === 'recovery' && <p className="ad-quiet" data-testid="rec-note-fee">{t('rec.feeNote')}</p>}
        {tab === 'cash' && <p className="ad-quiet" data-testid="rec-note-cash-path">{t('cash.pathNote')}</p>}
      </SystemNotes>
      <LiveNotice tone="info" value={note} onDismiss={() => setNote(null)} />

      {tab === 'npl' && (
        <div role="tabpanel" id="rec-panel-npl" aria-labelledby="rec-tab-npl" className="ad-section">
```

Delete `:353` `          <Notice tone="quiet">{t('rec.feeNote')}</Notice>` and `:460-461` (`          <Notice tone="quiet">{t('rec.cashRule')}</Notice>` and `          <Notice tone="quiet">{t('cash.pathNote')}</Notice>`). Leave `:448`, `:658-663` and `:681` as they are. `Notice` stays imported (still used).

`frontend/src/screens/InvoicePipeline.jsx`: after `:12` add `import { SystemNotes } from '../components/SystemNotes.jsx'`. Replace `:582-584`

```jsx
      {meta.invoice_owner_role && (
        <Notice tone="quiet">{t('pipe.owner', { role: codeLabel(meta.invoice_owner_role, lang, 'team') })}</Notice>
      )}
```

with

```jsx
      {/* Feedback Round 1, WP7 / F10 (a): the screen's one standing notice, folded.
          It keeps its own Notice (role="status") inside the fold — the fold is a
          native <details> that never unmounts or hides its children, so the note is
          still found by role (InvoicePipeline.test.jsx:102). */}
      <SystemNotes>
        {meta.invoice_owner_role && (
          <Notice tone="quiet">{t('pipe.owner', { role: codeLabel(meta.invoice_owner_role, lang, 'team') })}</Notice>
        )}
      </SystemNotes>
```

- [ ] **Step 8: Run the focused tests, the suite and the census**

Run: `npx vitest run src/components/SystemNotes.test.jsx src/screens/Today.notes.test.jsx src/screens/Recovery.test.jsx src/screens/Recovery.cash.test.jsx src/screens/Recovery.restructure.test.jsx src/screens/Recovery.lotprice.test.jsx src/screens/InvoicePipeline.test.jsx src/screens/Today.test.jsx src/round4.test.jsx src/today-density.test.jsx src/screens/Today.board.test.jsx src/i18n.test.js src/css-chain.test.js src/screens/Reminders.test.jsx`
Expected (measured on a scratch copy): 14 files, 179 tests, all PASS.

Run: `npx vitest run 2>&1 | tail -4`
Expected: Step 1's count **+ 2 files, + 10 tests** (3 + 5 created, 1 + 1 appended). Paste it.

Run: `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected (measured): `TODAY  chrome=105  perRow=31  at 50 rows=1655` and `visible=1655`. Paste both.

- [ ] **Step 9: Commit**

```bash
MSG=$(mktemp)
cat > "$MSG" <<'EOF'
feat(notes): one folded "หมายเหตุระบบ (n)" on Today, Recovery and the pre-install invoices

Design WP7 / F10 (a). The standing notices fold into a native <details>, shut by
default, every note always rendered inside it: the refusal bands keep their ids for
the column marks, every test id stays reachable, and the pipeline's owner notice
keeps role="status". Per-case facts on Recovery's cards stay on the cards.

No pinned test moves. Today density: chrome 108 -> 105, per row 31, page 1,658 -> 1,655.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/components/SystemNotes.jsx frontend/src/components/SystemNotes.test.jsx frontend/src/screens/Today.notes.test.jsx
git commit -F "$MSG" -- frontend/src/components/SystemNotes.jsx frontend/src/components/SystemNotes.test.jsx frontend/src/screens/Today.notes.test.jsx frontend/src/screens/Today.jsx frontend/src/screens/Recovery.jsx frontend/src/screens/InvoicePipeline.jsx frontend/src/screens/Recovery.test.jsx frontend/src/screens/InvoicePipeline.test.jsx frontend/src/realign.css frontend/src/i18n-journey.js
```

---

### Task B2a: `GET /v1/today` filters that refuse unknown values, and the numbers the filter bar prints

**Files:**
- Modify: `backend/app/today.py:52` (constants and three helpers added after `PTP_HISTORY_NOTE_TH`), `:186-190` (`build` signature and docstring), `:206-216` (case-level filters), `:220-221` (product filter), `:225-226` (tier count and tier filter), `:293-294` (meta keys)
- Modify: `backend/app/routers/today.py:145-152` (`_valid_choice` and the `today` route)
- Test: `backend/tests/test_today_filters.py` (create)

**Interfaces:**
- Consumes: `officers.registry()` (`officers.py:27`, rows with `uid`), `cases_domain.PAYMENT_STATUSES` (the five, REQ-COL-075), `dictionaries.for_current().list("DC_STATUS")` (rows with `code`), `today_domain.TIERS`, `_valid_rung` (`routers/today.py:117`), `errors.validation_failed(errors)` (`errors.py:240`).
- Produces:
  - `GET /v1/today?officer=&tier=&payment_status=&dc_status=&product=&q=&ladder_indicative=` — every value optional; an empty value is no filter. An unknown value is **422** `validation_failed` with `errors[0] = {"pointer": "/<field>", "code": "value_unknown", "message", "message_th", "known": [...]}`. Validation order: `ladder_indicative` (unchanged refusal), `officer`, `tier`, `payment_status`, `dc_status`, `product`; all of it before `detect_broken_ptps` runs. `q` is free text (trimmed, lower-cased, matched against display name, VOLT ID and customer number — the Work Book's search).
  - Known officers: `today.known_officers(cs, acting=None) -> [uid]` = registry uids, then any `officer_uid` on a case (the assign route accepts any uid), then the `X-Volt-Officer` identity (a new officer's own empty desk is never a refusal).
  - `today.product_of(item, case) -> "LEASE" | "CASH" | None` — the Work Book's rule (`routers/today.py:328`): no sheet facts → None; SPV → LEASE; otherwise CASH. `today.PRODUCTS = ("LEASE", "CASH")`.
  - `today.officer_totals(cs, known) -> {uid: int}` — each officer's whole list today, equal to `meta.total` of `/v1/today?officer=<uid>` with no other filter; zero for a known officer with nothing.
  - `today.build(officer=None, business_date=None, ladder_indicative=None, only_tier=None, payment_status=None, dc_status=None, product=None, q=None)` — every existing call (`reports.py:113,163`, `_workbook` `:304`) is keyword-compatible and gets the same `items`.
  - New `meta` keys on `/v1/today` (and on every `build()` result): `tier_counts: {TIER: int}` for all seven tiers (every filter applied except the tier filter; equals `counts_by_tier` when no tier filter), `officer_totals: {uid: int}`, `officer_totals_note_th: str`, `filters: {"officer", "tier", "payment_status", "dc_status", "product", "q"}` (what ran; `q` as matched, lower-cased). No item gains a key (the seven-key CLOSED-row diff at `test_round4.py:775` holds).

**Pins:** 0, measured. `test_round4.py:712-722` (thip 74, ladder filter 34), `:725-734` (the rung refusal is still `errors[0]` when combined), `:737-744`, `:760-775`; `test_round3.py:114`; `e2e_check.py:859,884,920` call `/v1/today` with no parameters. No density change (backend only).

- [ ] **Step 1: Re-measure**

Run: `git log --oneline -3 && git status --short`, then from `backend/`: `VOLT_TEST_PG_URL="postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data" .venv/bin/python -m pytest 2>&1 | tail -3`
Expected: the backend count (1,022 passed / 11 skipped at `caddc4b`; a scratch copy of `b5bdc7c` with this task applied measured 1,040 passed / 11 skipped, i.e. 1,027 before it). Paste it.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_today_filters.py` (create):

```python
"""Feedback Round 1, WP7 / B2 — Today's filter bar is served, and it refuses what it
does not know.

The tier strip and the "whole team today" panel became one filter bar (design WP7).
Every number the bar shows is the server's: `meta.tier_counts` (the tier options'
counts, under every filter except the tier filter) and `meta.officer_totals` (each
officer's whole list today — the numbers the old panel fetched with one /v1/today
call per officer). Every value the bar can send is validated; an unknown one is a
422 carrying the known list, never a silently empty or silently unfiltered desk.

Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import officers
from app import today as today_domain
from app.main import app


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    return TestClient(app)


def _today(client, **params):
    response = client.get("/v1/today", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize("field,value", [
    ("tier", "ALMOST_ROUTINE"),
    ("payment_status", "PAID"),
    ("dc_status", "BANANA"),
    ("product", "LOAN"),
    ("officer", "nobody-at-all"),
])
def test_an_unknown_filter_value_is_refused_with_the_known_list(client, field, value):
    response = client.get("/v1/today", params={field: value})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "validation_failed"
    error = body["errors"][0]
    assert error["pointer"] == "/" + field
    assert error["code"] == "value_unknown"
    assert error["known"] and value not in error["known"]
    assert _thai(error["message_th"])


def test_an_empty_filter_is_no_filter(client):
    everyone = _today(client)
    blank = _today(client, tier="", payment_status="", dc_status="", product="", q="", officer="")
    assert blank["meta"]["total"] == everyone["meta"]["total"]
    assert blank["meta"]["filters"] == {"officer": None, "tier": None, "payment_status": None,
                                        "dc_status": None, "product": None, "q": None}


def test_the_tier_filter_narrows_the_desk_and_its_options_keep_every_tiers_count(client):
    everyone = _today(client)
    counts = everyone["meta"]["tier_counts"]
    assert set(counts) == set(today_domain.TIERS)
    # With no tier filter the options' counts ARE the partition the chips used to draw.
    assert counts == everyone["meta"]["counts_by_tier"]
    tier = next(t for t in today_domain.TIERS if 0 < counts[t] < everyone["meta"]["total"])
    only = _today(client, tier=tier)
    assert only["meta"]["total"] == counts[tier] == len(only["items"])
    assert {i["tier"] for i in only["items"]} == {tier}
    assert sum(only["meta"]["counts_by_tier"].values()) == only["meta"]["total"]
    assert only["meta"]["next_up"] in {i["customer"]["uid"] for i in only["items"]} | {None}
    # The options still say what every OTHER tier would show — the filter bar never
    # tells an officer that the tier they are not looking at is empty.
    assert only["meta"]["tier_counts"] == counts
    assert only["meta"]["filters"]["tier"] == tier


def test_payment_status_dc_status_and_product_narrow_the_desk_the_work_book_way(client):
    everyone = _today(client)["items"]
    late = _today(client, payment_status="LATE")
    assert late["meta"]["total"] == sum(1 for i in everyone if i["case"]["payment_status"] == "LATE") > 0
    assert all(i["case"]["payment_status"] == "LATE" for i in late["items"])

    code = next(i["case"]["dc_status"] for i in everyone if i["case"]["dc_status"])
    narrowed = _today(client, dc_status=code)
    assert narrowed["meta"]["total"] == sum(1 for i in everyone if i["case"]["dc_status"] == code)

    for product in today_domain.PRODUCTS:
        expected = [i for i in everyone
                    if i["case"]["sheet"] and ("LEASE" if i["entity"] == "SPV" else "CASH") == product]
        assert _today(client, product=product)["meta"]["total"] == len(expected)
    # The Work Book applies the same rule and also serves CLOSED rows; its open rows agree.
    book = client.get("/v1/workbook", params={"product": "LEASE"}).json()["rows"]
    assert len([r for r in book if r["case"]["payment_status"] != "CLOSED"]) == \
        _today(client, product="LEASE")["meta"]["total"]


def test_the_search_box_matches_name_volt_id_and_customer_no(client):
    row = _today(client)["items"][0]
    for needle in (row["customer"]["display_name"][:4], row["case"]["volt_id"], row["customer"]["customer_no"]):
        if not needle:
            continue
        hits = _today(client, q=needle.upper())["items"]
        assert row["customer"]["uid"] in {i["customer"]["uid"] for i in hits}, needle
    assert _today(client, q="zz-no-such-customer-zz")["meta"]["total"] == 0


def test_officer_totals_are_each_officers_own_list_and_name_the_whole_team(client):
    meta = _today(client)["meta"]
    totals = meta["officer_totals"]
    assert {row["uid"] for row in officers.registry()} <= set(totals)
    for uid, n in totals.items():
        assert _today(client, officer=uid)["meta"]["total"] == n, uid
    # They are desk sizes, not a facet: another filter never moves them.
    assert _today(client, payment_status="NPL")["meta"]["officer_totals"] == totals
    assert _thai(meta["officer_totals_note_th"])


def test_an_officer_a_lead_assigned_work_to_is_a_filter_the_desk_accepts(client):
    uid = _today(client)["items"][0]["customer"]["uid"]
    assigned = client.post("/v1/customers/%s/assign" % uid, headers={"X-Volt-Role": "MANAGER"},
                           json={"officer_uid": "newhire"})
    assert assigned.status_code == 200
    body = _today(client, officer="newhire")
    assert [i["customer"]["uid"] for i in body["items"]] == [uid]
    assert body["meta"]["officer_totals"]["newhire"] == 1


def test_the_acting_officers_own_empty_desk_is_never_a_refusal(client):
    body = client.get("/v1/today", params={"officer": "newhire"}, headers={"X-Volt-Officer": "newhire"})
    assert body.status_code == 200
    assert body.json()["meta"]["total"] == 0 and body.json()["items"] == []
    # Someone else's unknown name is still refused.
    assert client.get("/v1/today", params={"officer": "newhire"}, headers={"X-Volt-Officer": "nantapol"}).status_code == 422


def test_the_filters_combine_and_the_ladder_filter_is_still_refused_first(client):
    both = _today(client, officer="thip", payment_status="LATE")
    assert all(i["case"]["officer_uid"] == "thip" and i["case"]["payment_status"] == "LATE" for i in both["items"])
    refused = client.get("/v1/today", params={"ladder_indicative": "ALMOST_NPL", "tier": "NOPE"})
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["pointer"] == "/ladder_indicative"
```

- [ ] **Step 3: Run them and watch them fail**

Run: `VOLT_TEST_PG_URL=… .venv/bin/python -m pytest tests/test_today_filters.py`
Expected (measured against HEAD): 13 FAILED — the five parametrised refusals get 200 instead of 422; `KeyError: 'filters'`, `'tier_counts'`, `'officer_totals'`; the payment-status narrowing returns the whole desk; the acting-officer test gets 200 where the stranger's name must be 422.

- [ ] **Step 4: Implement**

Apply exactly this change to `backend/app/today.py` (it applies cleanly to HEAD: `git apply --check` passed on it):

```diff
--- a/backend/app/today.py
+++ b/backend/app/today.py
@@ -51,6 +51,51 @@
 # claim about a desk with no promise history to explain (§1a).
 PTP_HISTORY_NOTE_TH = ("ยังไม่มีนัดที่บันทึกว่าชำระตามนัดในระบบ — ชีตบันทึกเฉพาะยอดและวันนัด "
                        "ไม่ได้บันทึกผล นัดที่เลยวันจึงขึ้นเป็นผิดนัดจนกว่าจะปิดนัดจากหน้าเคส")
+
+# Feedback Round 1, WP7 (B2): Today's filter bar. The product rule is the Work Book's
+# own (routers/today.py `_workbook`): a case with sheet facts on an SPV contract is a
+# lease, any other case with sheet facts is cash, a case with none has no product.
+PRODUCTS = ("LEASE", "CASH")
+OFFICER_TOTALS_NOTE_TH = ("จำนวนรายการในลิสต์วันนี้ของเจ้าหน้าที่แต่ละคน ไม่ขึ้นกับตัวกรองอื่น "
+                          "— ตัวเลขเดียวกับที่เจ้าหน้าที่คนนั้นเห็นเมื่อเปิดหน้าวันนี้ของตัวเอง")
+
+
+def product_of(item, case):
+    if not case.get("sheet"):
+        return None
+    return "LEASE" if item.get("entity") == "SPV" else "CASH"
+
+
+def known_officers(cs, acting=None):
+    """Every officer uid /v1/today may be filtered by, in registry order: the registry
+    (the seed's officers, then the fixed Manager, Owner and OPS seats), then any uid a
+    lead has assigned a case to since — POST /v1/customers/{uid}/assign takes the uid
+    as given, so a desk can exist for a name the registry never listed — then the
+    acting person's own identity (X-Volt-Officer): a new officer with nothing assigned
+    yet opens an empty desk, never a refusal."""
+    from . import officers
+    known = [row["uid"] for row in officers.registry()]
+    seen = set(known)
+    for uid in [case.get("officer_uid") for case in cs.cases.values()] + [acting]:
+        if uid and uid not in seen:
+            seen.add(uid)
+            known.append(uid)
+    return known
+
+
+def officer_totals(cs, known):
+    """B2: the team-workload numbers, served once instead of the screen calling
+    /v1/today once per officer (J4-17 / J5-11). Each officer's whole list today —
+    exactly `meta.total` of /v1/today?officer=<uid> with no other filter, because it
+    applies build()'s own two gates (a case on a book customer, not CLOSED). Zero for
+    an officer with nothing today, so a lead still sees the empty desk."""
+    totals = {uid: 0 for uid in known}
+    for customer in journey.book_customers():
+        case = cs.cases.get(customer.uid)
+        if case is None or case["payment_status"] in ("CLOSED",) or not case["officer_uid"]:
+            continue
+        totals[case["officer_uid"]] = totals.get(case["officer_uid"], 0) + 1
+    return totals
 
 
 def missed_equivalent(customer, item, missed):
@@ -183,12 +228,20 @@
     return last
 
 
-def build(officer=None, business_date=None, ladder_indicative=None):
+def build(officer=None, business_date=None, ladder_indicative=None, only_tier=None,
+          payment_status=None, dc_status=None, product=None, q=None):
     """Returns {items, meta}. Items carry the journey work item plus the case.
 
     Round-4 F2-CR-1: ladder_indicative narrows to the rung named — filtered here,
     before tiering, so counts_by_tier, total and next_up all follow the narrowed
-    set rather than being computed against the whole book and then sliced."""
+    set rather than being computed against the whole book and then sliced.
+
+    Feedback Round 1, WP7 (B2): only_tier, payment_status, dc_status, product and q
+    narrow the desk the same way, before next_up, the partition and the total. The
+    route validates every value first (routers/today.py); build() trusts its input.
+    `meta.tier_counts` counts under every filter EXCEPT only_tier, so the tier filter's
+    own options can say what each tier would show (with no tier filter it equals
+    counts_by_tier). `meta.officer_totals` is each officer's whole list today."""
     from .routers.journey import _work_item, _aggregate
     business_date = business_date or settings.business_date
     jstate = journey.for_current()
@@ -205,6 +258,8 @@
                 {"kind": "PEAK_REJECTED", "ref": rec["uid"], "text": rec.get("rejection_reason")})
     items = []
     reminders = []
+    needle = (q or "").strip().lower() or None
+    tier_counts = {t: 0 for t in TIERS}
     for customer in journey.book_customers():
         case = cs.cases.get(customer.uid)
         if case is None:
@@ -213,17 +268,33 @@
             continue
         if case["payment_status"] in ("CLOSED",):
             continue
+        # B2: the case-level filters, before the work item is built — they need no money.
+        # The search matches what the Work Book's search matches: name, VOLT ID, customer no.
+        if payment_status and case["payment_status"] != payment_status:
+            continue
+        if dc_status and case["dc_status"] != dc_status:
+            continue
+        if needle and not (needle in (customer.display_name or "").lower()
+                           or needle in (case["volt_id"] or "").lower()
+                           or needle in (customer.customer_no or "").lower()):
+            continue
         item = _work_item(jstate, customer, business_date)
         # Round-4 F2-CR-1: filtered BEFORE tiering, so everything downstream (missed,
         # tier_for, the sort, the partition, elsewhere, unlocked, next_up) sees only
         # the narrowed set — never a screen headed "filtered" over an unfiltered total.
         if ladder_indicative and (item.get("ladder") or {}).get("indicative") != ladder_indicative:
             continue
+        if product and product_of(item, case) != product:
+            continue
         missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
         missed, missed_basis_th = missed_equivalent(customer, item, missed)
         waiting = waiting_by_customer.get(customer.uid, [])
         tier, reason_th = tier_for(case, item, missed, business_date, waiting,
                                    missed_basis_th=missed_basis_th, customer=customer)
+        # B2: counted before the tier filter — these are the tier options' own numbers.
+        tier_counts[tier] += 1
+        if only_tier and tier != only_tier:
+            continue
         item["tier"] = tier
         item["tier_rank"] = TIER_RANK[tier]
         # Round-4 J4-29: a cash book has no monthly instalments to miss, so the chip an
@@ -291,7 +362,14 @@
                  # 6, never varies by officer/session/band set. Echoed so a client can
                  # assert the filter it sent is the filter that ran (R4-F56's class).
                  "ladder_rungs": ladder_mod.ladder_rungs(),
-                 "ladder_indicative": ladder_indicative},
+                 "ladder_indicative": ladder_indicative,
+                 # Feedback Round 1, WP7 (B2): the filter bar's served numbers and the
+                 # filters that actually ran, echoed the way ladder_indicative is above.
+                 "tier_counts": tier_counts,
+                 "officer_totals": officer_totals(cs, known_officers(cs)),
+                 "officer_totals_note_th": OFFICER_TOTALS_NOTE_TH,
+                 "filters": {"officer": officer, "tier": only_tier, "payment_status": payment_status,
+                             "dc_status": dc_status, "product": product, "q": needle}},
     }
 
 
```

Apply exactly this change to `backend/app/routers/today.py` (also `git apply --check` clean):

```diff
--- a/backend/app/routers/today.py
+++ b/backend/app/routers/today.py
@@ -142,14 +142,48 @@
     return value
 
 
+def _valid_choice(field, value, known, message_th):
+    """Feedback Round 1 / B2: one refusal for every /v1/today filter — `_valid_position`'s
+    idiom (pointer, code value_unknown, message_th) with `_unknown_rung_error`'s known
+    list riding inside the error item, so a client never has to guess what is allowed.
+    Empty/absent means unfiltered, never a refusal."""
+    if not value:
+        return None
+    if value not in known:
+        raise errors.validation_failed([{
+            "pointer": "/%s" % field, "code": "value_unknown",
+            "message": "%s must be one of %s; %r is not." % (field, ", ".join(known), value),
+            "message_th": message_th, "known": list(known)}])
+    return value
+
+
 # --- Today --------------------------------------------------------------------------
 
 @router.get("/v1/today")
 def today(officer: str = Query(default=None), ladder_indicative: str = Query(default=None),
-          x_volt_role: str = Header(default="OFFICER")):
+          tier: str = Query(default=None), payment_status: str = Query(default=None),
+          dc_status: str = Query(default=None), product: str = Query(default=None),
+          q: str = Query(default=None),
+          x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
     cs = cases_domain.for_current()
+    # Feedback Round 1 / B2: every filter is validated BEFORE the broken-PTP sweep or any
+    # row is built. A filter that matched everything — or nothing — on a typo would be
+    # worse than an error (Task 14's ruling on `position`, applied to all six).
+    rung = _valid_rung(ladder_indicative)
+    officer = _valid_choice("officer", officer, today_domain.known_officers(cs, acting=(x_volt_officer or "").strip() or None),
+                            "ไม่รู้จักเจ้าหน้าที่ที่ระบุ กรุณาเลือกจากรายชื่อทีม")
+    tier = _valid_choice("tier", tier, today_domain.TIERS,
+                         "ไม่รู้จักลำดับความสำคัญที่ระบุ กรุณาเลือกจากเจ็ดขั้นที่กำหนด")
+    payment_status = _valid_choice("payment_status", payment_status, cases_domain.PAYMENT_STATUSES,
+                                   "ไม่รู้จักสถานะการชำระที่ระบุ กรุณาเลือกจากห้าสถานะที่กำหนด")
+    dc_status = _valid_choice("dc_status", dc_status,
+                              [v["code"] for v in dictionaries.for_current().list("DC_STATUS")],
+                              "ไม่รู้จักสถานะติดตามที่ระบุ กรุณาเลือกจากรายการสถานะ DC")
+    product = _valid_choice("product", product, today_domain.PRODUCTS,
+                            "ไม่รู้จักผลิตภัณฑ์ที่ระบุ รับเฉพาะ LEASE หรือ CASH")
     cases_domain.detect_broken_ptps(cs, settings.business_date)
-    return today_domain.build(officer=officer, ladder_indicative=_valid_rung(ladder_indicative))
+    return today_domain.build(officer=officer, ladder_indicative=rung, only_tier=tier,
+                              payment_status=payment_status, dc_status=dc_status, product=product, q=q)
 
 
 @router.get("/v1/today/reminders")
```

Notes for the implementer, each one measured:
- `build()`'s new tier argument is `only_tier`, not `tier`: the loop already rebinds a local `tier` from `tier_for(...)`, which would overwrite a parameter of that name after the first row.
- `tier_counts[tier] += 1` sits after `tier_for` and before the tier filter, and after the product, ladder, status and search filters — so the tier options count "everything else I filtered by".
- `officer_totals` ignores every filter on purpose (desk sizes, not a facet); its test proves `officer_totals[x] == total(officer=x)` for every officer.
- Python 3.9: no `match`, no `X | Y` — the diff has neither.

- [ ] **Step 5: Run the focused tests, then the suite**

Run: `VOLT_TEST_PG_URL=… .venv/bin/python -m pytest tests/test_today_filters.py tests/test_round4.py tests/test_round3.py tests/test_today_and_pipeline.py tests/test_auth_http.py`
Expected (measured): 112 passed.

Run: `VOLT_TEST_PG_URL=… .venv/bin/python -m pytest 2>&1 | tail -3`
Expected: Step 1's count **+ 13 passed**, 11 skipped, 0 failed (measured on a scratch copy of `b5bdc7c`: 1,040 passed, 11 skipped). Paste it. Then `./scripts/verify_all.sh` from the repo root: EVERYTHING PASSED, e2e 31 of 31.

- [ ] **Step 6: Commit**

```bash
MSG=$(mktemp)
cat > "$MSG" <<'EOF'
feat(today): /v1/today filters by tier, payment status, DC status, product and search, and refuses a value it does not know

Design WP7 (B2). Every filter is validated before any row is built: an unknown value is
a 422 naming the field and listing the known values, never a silently empty or
unfiltered desk. The officer filter accepts the registry, any uid a case is assigned
to, and the caller's own identity. meta.tier_counts (every filter but the tier filter)
and meta.officer_totals (each officer's whole list today) are the numbers Today's filter
bar prints, served once instead of one /v1/today call per officer.

No pinned test moves; build() keeps its existing calls' items.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add backend/tests/test_today_filters.py
git commit -F "$MSG" -- backend/app/today.py backend/app/routers/today.py backend/tests/test_today_filters.py
```

---

### Task B2b: Today's FilterBar — the tier strip, the officer select and "whole team today" become one bar

**Files:**
- Test: `frontend/src/screens/Today.filter.test.jsx` (create)
- Modify: `frontend/src/components/SearchSelect.jsx:16`, `:22` (optional `buttonId`)
- Modify: `frontend/src/components/FilterBar.jsx:12`, `:26` (per-filter `emptyLabel`, `id`)
- Modify: `frontend/src/screens/Today.jsx` (HEAD `:15`, `:57`, `:164-172`, `:208`, `:232`, `:264`, `:283-290`, `:368-400`, `:463`, `:500`, `:603-641`, `:706-745`, `:763`, `:811-816`, `:819`, `:971-973`, `:1142-1144`, and B3's `systemNotes`)
- Modify: `frontend/src/i18n-today.js` (after B1's `today.remindersPage.sub`, both tables)
- Modify (edit 37): `frontend/src/screens/Today.test.jsx:196-203`, `:266-269`, `:445`, `:453`, `:490`, `:503`, `:508-509`, `:512-518`; `frontend/src/round4.test.jsx:661-663`, `:667-668`, `:766`

**Interfaces:**
- Consumes (B2a): `GET /v1/today` params `officer`, `tier`, `payment_status`, `dc_status`, `product`, `q`; `meta.tier_counts` `{TIER: int}`, `meta.officer_totals` `{uid: int}`, `meta.officer_totals_note_th`; the 422 `validation_failed` problem with `errors[].pointer`/`message_th`. `api.today(params)` (`api.js:235`, unchanged: `get()` drops empty values). `FilterBar({ filters, onChange, search, onSearch })` (`FilterBar.jsx:13`), which passes `className`/`labelClassName`/`triggerClassName` to `SearchSelect` already (`:20-22`).
- Produces:
  - `SearchSelect` prop `buttonId` (optional; default unchanged `${useId()}-button`). `FilterBar` filter fields `emptyLabel` (default `t('filter.all')`) and `id` (→ `buttonId`). WorkBook and Payments pass neither, so they render as before.
  - Today: `<FilterBar>` right after `</header>`, before `systemNotes`, in both views. Filters in order, test ids from `FilterBar`: `filter-tier` (label `today.tiers`; options `meta.tiers` in served order, labelled `today.filter.tierOption` `{tier} · {n} ราย` from `meta.tier_counts`, name only when not served), `filter-officer` (label `today.officer` "แสดงงานของ"; empty label `today.allOfficers` "ทุกคน"; trigger id `td-filter-officer`; options = served `officer_totals` keys ∪ officers seen, sorted, labelled `today.workloadRow` `{officer} · {n} ราย`, name only when not served), `filter-payment_status` (`book.filter.payment_status`; CURRENT, LATE, NPL, NOT_INSTALLED — CLOSED never lists on Today), `filter-dc_status` (`book.filter.dc_status`; active `DC_STATUS` dictionary codes, dictionary labels), `filter-product` (`book.filter.product`; LEASE, CASH), and the search box (`filter.search`, debounced 250 ms, the Work Book's `SEARCH_DEBOUNCE_MS`).
  - URL: `?officer=` keeps its rule (`""` = ทุกคน); `?tier=`, `?payment_status=`, `?dc_status=`, `?product=`, `?q=` hold the other filters; picking "ทั้งหมด" removes the key; a pick resets the page to 1.
  - Request: `api.today(query)` with only the set keys; an unfiltered desk still calls `api.today({ officer })` or `api.today(undefined)`.
  - Header sub line: `today-filtered` ("กรองอยู่") when any non-officer filter is set.
  - A 422 before the first load renders the `Problem` plus `today-filters-reset` (a link to `/`, `today.filter.reset`).
  - Into B3's fold: `answers-elsewhere` (and `answers-elsewhere-go` in list view, same href `#td-waiting-<uid>`), prefixed by `tier.ANSWER_WAITING`; `officer-totals-note` (the served note) when `officer_totals` is served.
  - Gone from Today: `.td-tiers` / `.td-tier[data-tier-code]` chips, `team-workload` and `workload-total` (including the client-side `reduce` that summed the officers' totals — a sum `api.js:1-4` forbids), `select#td-officer`, the N+1 `/v1/today` calls per officer.
  - i18n keys (i18n-today.js, both tables): `today.filter.tierOption`, `today.filter.on`, `today.filter.reset`. Reused unchanged: `today.tiers`, `today.officer`, `today.allOfficers`, `today.workloadRow`, `book.filter.payment_status|dc_status|product`, `book.product.*`, `status.*`, `tier.*`, `filter.*`. Left unused, not deleted (no test checks unused keys): `today.teamWorkload`, `today.teamWorkloadOpen`, `today.teamWorkloadNote`, `today.workloadTotal`, `today.workloadFailed`, `today.tierCount`, `today.whyCounts`.

**Pins:** edit 37 — `Today.test.jsx:196-203`, `:266-269`, `:445`, `:453`, `:490`, `:503`, `:508-509`, `:512-518` (6 tests) and `round4.test.jsx:661-663`, `:667-668`, `:766` (2 tests): 8 tests, 31 original lines, measured by running the suite with the implementation and no test change (exactly these 8 failed: "renders the seven tiers…", "filters by the officer query param…", "opens on the top-bar identity…", "refetches when the top-bar identity changes…", "prints tier_reason_th… (J3-04)", "J3-04: the tier chips sum…", "J4-17 … shows each officer’s own total…", "S5-02 … keeps the previous officer named…"). Held at 0: `Today.test.jsx:390-400` (the pick-officer button focuses `#td-filter-officer`, which `getByLabelText('แสดงงานของ')` returns), `:504`, `:521`, `round4.test.jsx:506-518`, all of `Today.board.test.jsx`, `WorkBook.test.jsx` (24) and `Payments.test.jsx` (18). Density: chrome 105 → **104**, row 31, page 1,655 → **1,654** (tier strip −29, officer label + select −4, FilterBar +32).

- [ ] **Step 1: Re-measure**

Run: `git log --oneline -3 && git status --short`, `npx vitest run 2>&1 | tail -4`, `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected: B3's count; `chrome=105  perRow=31  at 50 rows=1655`. B1 and B3 must both be committed (this task's patch is cut against their result).

- [ ] **Step 2: Grep the keys**

Run: `grep -n "today.filter\.\|td-filter-officer\|today-filtered\|today-filters-reset\|officer-totals-note" src/i18n-*.js src/screens/*.jsx src/components/*.jsx`
Expected: no output.

- [ ] **Step 3: Write the failing test**

`frontend/src/screens/Today.filter.test.jsx` (create):

```jsx
// Feedback Round 1, WP7 / B2: the tier strip and "whole team today" became ONE filter
// bar — the Work Book's own FilterBar — above the list and the board. Every value it
// sends is the server's to validate; every number it prints is the server's.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setOfficer, setRole } from '../components/role.jsx'
import TodayScreen from './Today.jsx'

vi.mock('../api.js', () => ({
  api: {
    today: vi.fn(), todayItemDone: vi.fn(), dictionary: vi.fn(), boardColumns: vi.fn(), boardMove: vi.fn(),
    logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(),
  },
}))

const TIERS = ['PTP_DUE_TODAY', 'NEXT_ACTION_DUE', 'BROKEN_PTP', 'AT_RISK_TWO_MISSED',
               'NEW_ARREARS', 'ANSWER_WAITING', 'ROUTINE']

const ITEM = (uid, over = {}) => ({
  customer: { uid, customer_no: `C-${uid}`, display_name: `ลูกค้า ${uid}`, phone_masked: '08x-xxx-0000',
              phone_e164: null, line_id: null, contract_count: 1, officer: 'nantapol' },
  entity: 'SPV', company_id: 'CO-SPV', aggregate_overdue: '2999.00', aggregate_outstanding: '212928.99',
  oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL',
  contact_lock: { state: 'OPEN' }, ladder: null, waiting: [], missed_count: 1,
  tier: 'BROKEN_PTP', tier_rank: 3, board_column_id: 'col-1',
  case: { uid: `case-${uid}`, payment_status: 'LATE', dc_status: 'NO_ACTION', next_action: 'CALL',
          next_action_on: '2026-10-23', kept_ptp_count: 0, broken_ptp_count: 1, open_ptp: null, officer_uid: 'nantapol' },
  ...over,
})

const RESPONSE = (over = {}) => ({
  run: { business_date: '2026-10-23' },
  items: [ITEM('cu-1'), ITEM('cu-2', { tier: 'ROUTINE', tier_rank: 7 })],
  meta: {
    total: 2, next_up: 'cu-1', tiers: TIERS,
    counts_by_tier: { BROKEN_PTP: 1, ROUTINE: 1 },
    tier_counts: { PTP_DUE_TODAY: 0, NEXT_ACTION_DUE: 0, BROKEN_PTP: 1, AT_RISK_TWO_MISSED: 4,
                   NEW_ARREARS: 0, ANSWER_WAITING: 0, ROUTINE: 1 },
    officer_totals: { nantapol: 63, noon: 7, owner: 0, ploy: 7, thip: 74 },
    officer_totals_note_th: 'จำนวนรายการในลิสต์วันนี้ของเจ้าหน้าที่แต่ละคน ไม่ขึ้นกับตัวกรองอื่น',
    ...over,
  },
})

const DICTS = {
  DC_STATUS: { name: 'DC_STATUS', values: [
    { code: 'NO_ACTION', label_th: 'ยังไม่ดำเนินการ', label_en: 'No Action', active: true },
    { code: 'CONTACT_BACK', label_th: 'ให้ติดต่อกลับ', label_en: 'Contact Back', active: true },
    { code: 'RETIRED_CODE', label_th: 'เลิกใช้', label_en: 'Retired', active: false },
  ] },
}

let lastSearch = ''
function SearchSpy() {
  lastSearch = useLocation().search
  return null
}
const Today = ({ entry = '/' } = {}) => (
  <MemoryRouter initialEntries={[entry]}><TodayScreen /><SearchSpy /></MemoryRouter>
)

function pick(filterKey, optionName) {
  fireEvent.click(screen.getByTestId(`filter-${filterKey}`))
  fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: optionName }))
}

function optionsOf(filterKey) {
  fireEvent.click(screen.getByTestId(`filter-${filterKey}`))
  const options = within(screen.getByRole('listbox')).getAllByRole('option')
  const read = options.map((o) => ({ value: o.getAttribute('data-value'), label: o.textContent }))
  fireEvent.click(screen.getByTestId(`filter-${filterKey}`))
  return read
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  lastSearch = ''
  setRole('OFFICER')
  setOfficer('nantapol')
  api.today.mockResolvedValue(RESPONSE())
  api.dictionary.mockImplementation((name) => Promise.resolve(DICTS[name] || { name, values: [] }))
  api.boardColumns.mockResolvedValue({ columns: [{ column_id: 'col-1', name: 'Call today', order: 1 }] })
})

describe('Today — the filter bar (WP7 / B2)', () => {
  it('draws one bar of five filters and a search box, and no tier strip, workload panel or native officer select', async () => {
    const { container } = renderIn('th', <Today />)
    await screen.findByTestId('filter-tier')
    const bar = container.querySelector('.fb')
    expect(bar).toHaveAttribute('role', 'search')
    expect([...bar.querySelectorAll('[data-testid^="filter-"]')].map((b) => b.getAttribute('data-testid')))
      .toEqual(['filter-tier', 'filter-officer', 'filter-payment_status', 'filter-dc_status', 'filter-product'])
    expect(within(bar).getByRole('searchbox', { name: 'ค้นหา' })).toBeInTheDocument()
    expect(container.querySelector('.td-tiers')).toBeNull()
    expect(screen.queryByTestId('team-workload')).toBeNull()
    expect(container.querySelector('select#td-officer')).toBeNull()
  })

  it('labels the tier options with the served tier_counts, in the served order', async () => {
    renderIn('th', <Today />)
    await screen.findByTestId('filter-tier')
    expect(optionsOf('tier')).toEqual([
      { value: '', label: 'ทั้งหมด' },
      { value: 'PTP_DUE_TODAY', label: 'PTP ถึงกำหนดวันนี้ · 0 ราย' },
      { value: 'NEXT_ACTION_DUE', label: 'งานถัดไปถึงกำหนด · 0 ราย' },
      { value: 'BROKEN_PTP', label: 'ผิดนัด PTP · 1 ราย' },
      { value: 'AT_RISK_TWO_MISSED', label: 'เสี่ยง — ค้างสองงวดขึ้นไป · 4 ราย' },
      { value: 'NEW_ARREARS', label: 'ค้างชำระใหม่ · 0 ราย' },
      { value: 'ANSWER_WAITING', label: 'รอคำตอบ · 0 ราย' },
      { value: 'ROUTINE', label: 'ติดตามตามรอบ · 1 ราย' },
    ])
  })

  it('an older server that serves no counts gets names without numbers, never a count made here', async () => {
    api.today.mockResolvedValue(RESPONSE({ tier_counts: undefined, officer_totals: undefined }))
    renderIn('th', <Today />)
    await screen.findByTestId('filter-tier')
    expect(optionsOf('tier').find((o) => o.value === 'BROKEN_PTP').label).toBe('ผิดนัด PTP')
    expect(optionsOf('officer').find((o) => o.value === 'nantapol').label).toBe('nantapol')
    expect(screen.queryByTestId('officer-totals-note')).toBeNull()
  })

  it('offers the whole team with each officer’s served total, "ทุกคน" first, and says what the numbers are', async () => {
    renderIn('th', <Today />)
    await screen.findByTestId('filter-officer')
    expect(optionsOf('officer')).toEqual([
      { value: '', label: 'ทุกคน' },
      { value: 'nantapol', label: 'nantapol · 63 ราย' },
      { value: 'noon', label: 'noon · 7 ราย' },
      { value: 'owner', label: 'owner · 0 ราย' },
      { value: 'ploy', label: 'ploy · 7 ราย' },
      { value: 'thip', label: 'thip · 74 ราย' },
    ])
    expect(screen.getByTestId('system-notes')).toContainElement(screen.getByTestId('officer-totals-note'))
  })

  it('a tier pick asks the server for that tier, keeps it in the URL, and "ทั้งหมด" takes it off', async () => {
    renderIn('th', <Today />)
    await screen.findByTestId('filter-tier')
    pick('tier', 'ผิดนัด PTP · 1 ราย')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol', tier: 'BROKEN_PTP' }))
    expect(lastSearch).toContain('tier=BROKEN_PTP')
    expect(await screen.findByTestId('today-filtered')).toHaveTextContent('กรองอยู่')
    pick('tier', 'ทั้งหมด')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol' }))
    expect(lastSearch).not.toContain('tier=')
  })

  it('payment status, DC status and product each travel under their own name; a retired DC code is not offered', async () => {
    renderIn('th', <Today />)
    await screen.findByTestId('filter-payment_status')
    expect(optionsOf('payment_status').map((o) => o.value)).toEqual(['', 'CURRENT', 'LATE', 'NPL', 'NOT_INSTALLED'])
    expect(optionsOf('dc_status').map((o) => o.value)).toEqual(['', 'NO_ACTION', 'CONTACT_BACK'])
    pick('payment_status', 'ค้างชำระ')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol', payment_status: 'LATE' }))
    pick('dc_status', 'ให้ติดต่อกลับ')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol', payment_status: 'LATE', dc_status: 'CONTACT_BACK' }))
    pick('product', 'เงินสด')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({
      officer: 'nantapol', payment_status: 'LATE', dc_status: 'CONTACT_BACK', product: 'CASH' }))
  })

  it('the search box asks once, after the officer stops typing', async () => {
    renderIn('th', <Today />)
    const box = await screen.findByRole('searchbox', { name: 'ค้นหา' })
    const before = api.today.mock.calls.length
    fireEvent.change(box, { target: { value: 'ก' } })
    fireEvent.change(box, { target: { value: 'กม' } })
    fireEvent.change(box, { target: { value: 'กมล' } })
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol', q: 'กมล' }))
    expect(api.today.mock.calls.length - before).toBe(1)
    expect(lastSearch).toContain('q=')
  })

  it('a desk opened from a URL that carries filters asks for them at once and shows them', async () => {
    renderIn('th', <Today entry="/?tier=BROKEN_PTP&product=LEASE&q=%E0%B8%81%E0%B8%A1%E0%B8%A5" />)
    await screen.findByTestId('filter-tier')
    expect(api.today).toHaveBeenCalledWith({ officer: 'nantapol', tier: 'BROKEN_PTP', product: 'LEASE', q: 'กมล' })
    expect(screen.getByTestId('filter-tier')).toHaveAttribute('data-value', 'BROKEN_PTP')
    expect(screen.getByTestId('filter-product')).toHaveAttribute('data-value', 'LEASE')
    expect(screen.getByRole('searchbox', { name: 'ค้นหา' })).toHaveValue('กมล')
  })

  it('a filter value the server refuses is shown as the refusal, with the way back to the whole desk', async () => {
    api.today.mockRejectedValue(Object.assign(new Error('/v1/today'), { status: 422, problem: {
      code: 'validation_failed', status: 422, message_th: 'ข้อมูลไม่ถูกต้อง',
      errors: [{ pointer: '/tier', code: 'value_unknown', message_th: 'ไม่รู้จักลำดับความสำคัญที่ระบุ', known: TIERS }],
    } }))
    renderIn('th', <Today entry="/?tier=OLD_TIER" />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('/tier')
    expect(alert).toHaveTextContent('ไม่รู้จักลำดับความสำคัญที่ระบุ')
    expect(screen.getByTestId('today-filters-reset')).toHaveAttribute('href', '/')
  })

  it('the board keeps the same bar, and a pick there asks for filtered cards', async () => {
    window.localStorage.setItem('volt.today.view', 'board')
    renderIn('th', <Today />)
    await screen.findByTestId('board')
    expect(screen.getByTestId('filter-tier')).toBeInTheDocument()
    pick('tier', 'ผิดนัด PTP · 1 ราย')
    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol', tier: 'BROKEN_PTP' }))
  })

  it('the answer waiting on a higher-tier row is said in the fold, with its jump, now that the chip is gone', async () => {
    api.today.mockResolvedValue({
      ...RESPONSE({ answers_waiting: 1, answers_waiting_elsewhere: 1 }),
      items: [ITEM('cu-1', { waiting: [{ uid: 'w-1', kind: 'TICKET_CLOSED', text_th: 'ปิดตั๋วแล้ว' }] })],
    })
    renderIn('th', <Today />)
    const go = await screen.findByTestId('answers-elsewhere-go')
    expect(screen.getByTestId('system-notes')).toContainElement(go)
    expect(go).toHaveAttribute('href', '#td-waiting-cu-1')
    expect(go.closest('p')).toHaveTextContent('รอคำตอบ · รวมอยู่ในขั้นอื่น 1')
  })
})
```

- [ ] **Step 4: Run it and watch it fail**

Run: `npx vitest run src/screens/Today.filter.test.jsx`
Expected: FAIL — 11 tests; `Unable to find an element by: [data-testid="filter-tier"]` (and the searchbox / `answers-elsewhere-go` in the fold for the others).

- [ ] **Step 5: Implement — SearchSelect and FilterBar**

Apply (`git apply --check` passed against HEAD):

```diff
--- a/frontend/src/components/SearchSelect.jsx
+++ b/frontend/src/components/SearchSelect.jsx
@@ -14,12 +14,14 @@
 export function SearchSelect({
   label, labelSuffix, value, options = [], emptyLabel, onChange,
   testid, searchTestid, className = '', labelClassName = '', triggerClassName = '',
-  query: controlledQuery, onQuery, searchPlaceholder,
+  query: controlledQuery, onQuery, searchPlaceholder, buttonId: givenButtonId,
 }) {
   const t = useT()
   const baseId = useId()
   const labelId = `${baseId}-label`
-  const buttonId = `${baseId}-button`
+  // Feedback Round 1 (B2): a caller that must move focus to this control from
+  // elsewhere on the page (Today's pick-your-name line) names the trigger's id.
+  const buttonId = givenButtonId || `${baseId}-button`
   const listId = `${baseId}-list`
   const [open, setOpen] = useState(false)
   const [localQuery, setLocalQuery] = useState('')
--- a/frontend/src/components/FilterBar.jsx
+++ b/frontend/src/components/FilterBar.jsx
@@ -9,7 +9,9 @@
 // keyboard already knows. Arina, 2026-09-13: every filter gets a search box inside
 // its list and a list that scrolls — SearchSelect rebuilds the keyboard contract.
 //
-// filters: [{ key, label, options: [{ value, label } | string], value }]
+// filters: [{ key, label, options: [{ value, label } | string], value, emptyLabel?, id? }]
+// `emptyLabel` names "no filter" where "All" would read wrong (Today's officer filter
+// says "Everyone"); `id` is the trigger's own id, for a caller that moves focus to it.
 export function FilterBar({ filters = [], onChange, search, onSearch }) {
   const t = useT()
   return (
@@ -23,7 +25,8 @@
           label={filter.label}
           value={filter.value}
           options={filter.options || []}
-          emptyLabel={t('filter.all')}
+          emptyLabel={filter.emptyLabel || t('filter.all')}
+          buttonId={filter.id}
           testid={`filter-${filter.key}`}
           onChange={(value) => onChange && onChange(filter.key, value)}
         />
```

- [ ] **Step 6: Implement — Today**

Apply this patch to `frontend/src/screens/Today.jsx` as B1 and B3 left it (`git apply --check` it first; it was produced from, and `patch --dry-run` verified against, a reconstruction of that state, which itself passes `today-density`, `Today.notes`, `Today.board`, `Reminders` and `SystemNotes` tests at chrome 105). If `--check` rejects a hunk only on blank-line context, apply that hunk by hand — each hunk's `-` lines are unique in the file.

```diff
--- a/frontend/src/screens/Today.jsx
+++ b/frontend/src/screens/Today.jsx
@@ -14,6 +14,7 @@
 import { TierChip } from '../components/TierChip.jsx'
 import { Notice, PendingBadge, LiveNotice } from '../components/Notice.jsx'
 import { SystemNotes } from '../components/SystemNotes.jsx'
+import { FilterBar } from '../components/FilterBar.jsx'
 import { Problem } from '../components/Problem.jsx'
 import { Spec } from '../components/Spec.jsx'
 import {
@@ -55,6 +56,19 @@
 const PAGE_SIZE = 50
 
 const KEY_TODAY_VIEW = 'volt.today.view'
+// Feedback Round 1, WP7 (B2): the tier strip and the "whole team today" panel became
+// ONE filter bar, the Work Book's own FilterBar. Its filters live in the URL beside
+// ?officer=, so a return navigation restores them for free (ruling 56 path 1) and a
+// refresh keeps the desk being read. The server validates every value (422 on one it
+// does not know) and serves every number the bar prints (meta.tier_counts,
+// meta.officer_totals) — nothing here counts rows to label an option.
+const TODAY_FILTER_KEYS = ['tier', 'payment_status', 'dc_status', 'product']
+// CLOSED is a valid payment status, but /v1/today never lists a CLOSED case, so
+// offering it would offer an always-empty desk. The server still accepts it.
+const TODAY_PAYMENT_STATUSES = ['CURRENT', 'LATE', 'NPL', 'NOT_INSTALLED']
+const TODAY_PRODUCTS = ['LEASE', 'CASH']
+const SEARCH_DEBOUNCE_MS = 250
+const OFFICER_FILTER_ID = 'td-filter-officer'
 // Ruling 51a: which fields a board card shows is a per-officer, per-browser
 // preference, held the same guarded way as the view choice — never sent to the
 // API (prefs.jsx's own law). `standard` is the default and is byte-identical to
@@ -151,14 +165,25 @@
   const [officers, setOfficers] = useState([])
   const [drawerFor, setDrawerFor] = useState(null)
   const [flash, setFlash] = useState(null)
-  // Round-4 J4-17: a lead balances the desk by four numbers no page showed —
-  // /v1/today had to be called once per officer. The panel calls it once per
-  // officer, on demand, and prints the SAME totals each of them sees.
-  const [workload, setWorkload] = useState(null)
   const [loadedFor, setLoadedFor] = useState(null)
   const loadSeq = useRef(0)
-  const [workloadBusy, setWorkloadBusy] = useState(false)
   const roster = useRoster()
+  // B2: the four choice filters and the search, read from the URL. The search box
+  // types into local state and reaches the URL (and so the request) after a pause,
+  // the Work Book's own debounce, so a name is one request rather than one per key.
+  const [tierFilter, paymentFilter, dcFilter, productFilter] = TODAY_FILTER_KEYS.map((key) => params.get(key) || '')
+  const urlQ = params.get('q') || ''
+  const [q, setQ] = useState(urlQ)
+  useEffect(() => {
+    if (q === urlQ) return undefined
+    const handle = setTimeout(() => {
+      const next = new URLSearchParams(params)
+      if (q) next.set('q', q)
+      else next.delete('q')
+      setParams(next, { replace: true })
+    }, SEARCH_DEBOUNCE_MS)
+    return () => clearTimeout(handle)
+  }, [q, urlQ, params, setParams])
   // R-VIEW: list is the shipped default (ruling 24); a choice of board is kept
   // per browser, never sent to the API — it is how this person reads the
   // screen, not what the run computed (the same law prefs.jsx already states
@@ -194,7 +219,6 @@
     setDensity(next)
     writePref(KEY_TODAY_CARD, next)
   }
-  const officerSelect = useRef(null)
   // P2: one expanded row at a time, across every tier section on the page.
   const expand = useRowExpand()
   // Reading-order §2.3 (a-2): one fold on the hero — never more than one hero
@@ -218,7 +242,16 @@
     const want = officer
     loadSeq.current += 1
     const seq = loadSeq.current
-    api.today(officer ? { officer } : undefined)
+    // B2: only the filters that are set travel. An unfiltered desk still asks exactly
+    // `{ officer }` or nothing — the shape App.jsx's rail badge asks too.
+    const query = {}
+    if (officer) query.officer = officer
+    if (tierFilter) query.tier = tierFilter
+    if (paymentFilter) query.payment_status = paymentFilter
+    if (dcFilter) query.dc_status = dcFilter
+    if (productFilter) query.product = productFilter
+    if (urlQ) query.q = urlQ
+    api.today(Object.keys(query).length ? query : undefined)
       .then((d) => {
         if (seq !== loadSeq.current) return
         setLoadedFor(want)
@@ -250,7 +283,7 @@
         }
       })
       .catch((e) => { if (seq === loadSeq.current) setProblem(fromError(e)) })
-  }, [officer, roster])
+  }, [officer, tierFilter, paymentFilter, dcFilter, productFilter, urlQ, roster])
   useEffect(() => { load() }, [load])
   // Ruling 56 path 1: router state, not sessionStorage, carries "this navigation
   // IS a return" — state is per-history-entry and dies on refresh, which is
@@ -269,15 +302,6 @@
     }
     // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [location.key])
-  // Round-5 J5-11 (its second round): the lead pressed this panel open and it stayed
-  // "—". Rather than depend on a click reaching the right element, the one number a
-  // lead needs is fetched as soon as a lead opens the page.
-  const leadRole = role === 'SUPERVISOR' || role === 'MANAGER' || role === 'OWNER'
-  useEffect(() => {
-    if (leadRole && workload === null && !workloadBusy) loadWorkload()
-    // eslint-disable-next-line react-hooks/exhaustive-deps
-  }, [leadRole])
-
   // R-COL: the board's four columns are a served, team-owned list
   // (`GET /v1/board/columns`) — never a client constant, never matched by name.
   // Loaded once; it does not vary by officer.
@@ -344,40 +368,6 @@
     }
   }
 
-  // One call per officer, because /v1/today is per officer — the numbers are the
-  // API's own totals, never re-counted here. A name whose list refuses is said to
-  // have refused rather than shown as zero.
-  async function loadWorkload() {
-    if (workloadBusy) return
-    setWorkloadBusy(true)
-    // Round-5 S5-01: the lead pressed this four times and the panel stayed "—".
-    // Anything thrown while building the list left workloadBusy stuck true, and the
-    // guard above then swallowed every later press in silence. The whole body is in
-    // try/finally now, the sources are guarded, and the calls run together so the
-    // panel answers in one round trip rather than six.
-    try {
-      const names = [...new Set([
-        ...(Array.isArray(roster) ? roster : []).map((o) => o?.uid),
-        ...(Array.isArray(officers) ? officers : []),
-        ...OFFICERS,
-      ])].filter(Boolean).sort()
-      const rows = await Promise.all(names.map(async (name) => {
-        try {
-          const d = await api.today({ officer: name })
-          return { officer: name, total: d?.meta?.total ?? (d?.items || []).length }
-        } catch {
-          return { officer: name, total: null }
-        }
-      }))
-      setWorkload(rows)
-    } catch (e) {
-      setProblem(fromError(e))
-      setWorkload([])
-    } finally {
-      setWorkloadBusy(false)
-    }
-  }
-
   const items = data?.items || []
   const meta = data?.meta || {}
   const tiers = meta.tiers || []
@@ -429,6 +419,21 @@
     setParams(next)
   }
 
+  // B2: one handler for the bar. The officer keeps its own rule above; every other
+  // filter is set, or removed when "ทั้งหมด" is picked, and the list starts again at
+  // its first page.
+  function onFilter(key, value) {
+    if (key === 'officer') {
+      chooseOfficer(value)
+      return
+    }
+    const next = new URLSearchParams(params)
+    if (value) next.set(key, value)
+    else next.delete(key)
+    setParams(next)
+    setPage(0)
+  }
+
   // Round-3 J3-35: the only way to move a customer to another officer was one
   // hand-typed uid at a time on /settings. The row the lead is looking at can do
   // it, for the roles the API lets assign; an older client without the route
@@ -464,7 +469,19 @@
     result: (code) => dictLabel(contactResults.values, code, lang),
   }
 
-  if (problem && !data) return <Problem problem={problem} endpoint="/v1/today" />
+  // B2: a filter the server does not know (a stale bookmark, a hand-edited URL) is a
+  // refusal with the known values listed, never a silently unfiltered desk; the way
+  // out is the unfiltered desk, one click away.
+  if (problem && !data) {
+    return (
+      <div className="td-page">
+        <Problem problem={problem} endpoint="/v1/today" />
+        {problem.code === 'validation_failed' && (
+          <p><Link className="btn btn--sm" to="/" data-testid="today-filters-reset">{t('today.filter.reset')}</Link></p>
+        )}
+      </div>
+    )
+  }
   if (!data) return <p className="empty">{t('common.loading')}</p>
 
   // Round-3 J3-04: ONE number per tier. The chip counts the rows that are IN the
@@ -542,86 +559,36 @@
     </p>
   )
 
-  // B2-F1: the seven tier chips and `answers-elsewhere-go` are `<a href="#td-tier-…">`
-  // / `<a href="#td-waiting-…">` anchors that target the list's own `td-group`
-  // sections — sections board view never renders (Today.jsx `boardColumns`/`BoardView`
-  // below). Eight dead anchors, live since the first board build. In board view the
-  // chip takes the SAME non-link branch the component already has for a zero count
-  // (`td-tier--static`, not `td-tier--empty`, whose dashed border would falsely claim
-  // the count is zero) and the jump degrades to the existing plain-span branch.
-  const tiersBlock = (
-    <ul className="td-tiers" aria-label={t('today.tiers')}>
-      {tiers.map((tier) => {
-        const n = tierCount(tier)
-        const chip = (
-          <>
-            <TierChip reason={tier} />
-            <span className="td-tier__count" data-count={n}>{t('today.tierCount', { n })}</span>
-          </>
-        )
-        return (
-          <li key={tier}>
-            {view === 'board'
-              ? <span className="td-tier td-tier--static" data-tier-code={tier}>{chip}</span>
-              : n === 0
-                ? <span className="td-tier td-tier--empty" data-tier-code={tier}>{chip}</span>
-                : <a className="td-tier" href={`#td-tier-${tier}`} data-tier-code={tier}>{chip}</a>}
-            {tier === 'ANSWER_WAITING' && answersElsewhere > 0 && (
-              view === 'board' || !firstWaitingUid ? (
-                <span className="td-tier__jump" data-testid="answers-elsewhere">{t('today.answersElsewhere', { n: answersElsewhere })}</span>
-              ) : (
-                <a className="td-tier__jump" href={`#td-waiting-${firstWaitingUid}`} data-testid="answers-elsewhere-go">
-                  <span data-testid="answers-elsewhere">{t('today.answersElsewhere', { n: answersElsewhere })}</span>
-                  {' · '}{t('today.answersElsewhereGo')}
-                </a>
-              )
-            )}
-          </li>
-        )
-      })}
-    </ul>
-  )
-
-  const workloadBlock = (role === 'SUPERVISOR' || role === 'MANAGER' || role === 'OWNER') && (
-    <details className="td-reminders" data-testid="team-workload">
-      <summary onClick={() => { if (workload === null) loadWorkload() }}>
-        <span>{t('today.teamWorkload')}</span>
-        <span className="td-tier__count">{workload ? workload.length : '—'}</span>
-      </summary>
-      <p className="td-quiet">{t('today.teamWorkloadNote')}</p>
-      {workload === null ? (
-        <p className="td-reminders__empty">
-          <button type="button" className="btn btn--sm" onClick={loadWorkload} disabled={workloadBusy}>
-            {workloadBusy ? t('common.loading') : t('today.teamWorkloadOpen')}
-          </button>
-        </p>
-      ) : (
-        <>
-          <ul className="td-workload">
-            {workload.map((w) => (
-              <li key={w.officer} data-workload={w.officer}>
-                {/* Round 5, label pass §3.1 (V1 split) — PROPOSED, NOT BUILT: leg B's
-                    `today.workloadRowGo` split moves an assertion leg B did not
-                    find in a static grep — `round4.test.jsx:661/:662` query this
-                    exact button by `today.workloadRow`'s current text
-                    ("thip · 74 ราย"). Per the round's own rule (zero assertions
-                    move on the 30 safe items), reverted and escalated rather than
-                    absorbed; see C-changes.md. */}
-                <button type="button" className="btn btn--sm" onClick={() => chooseOfficer(w.officer)}>
-                  {w.total === null
-                    ? t('today.workloadFailed', { officer: w.officer })
-                    : t('today.workloadRow', { officer: w.officer, n: w.total })}
-                </button>
-              </li>
-            ))}
-          </ul>
-          <p className="td-quiet" data-testid="workload-total">
-            {t('today.workloadTotal', { n: workload.reduce((a, w) => a + (w.total || 0), 0) })}
-          </p>
-        </>
-      )}
-    </details>
-  )
+  // B2: the bar's five filters. Option labels carry the SERVED numbers — the tier
+  // options `meta.tier_counts` (every filter except the tier filter itself, so the
+  // tiers not chosen still say what they hold) and the officer options
+  // `meta.officer_totals` (each officer's whole list today, the team-workload data).
+  // An older server that serves neither gets names without numbers, never a count
+  // made up here.
+  const tierCounts = meta.tier_counts && typeof meta.tier_counts === 'object' ? meta.tier_counts : null
+  const officerTotals = meta.officer_totals && typeof meta.officer_totals === 'object' ? meta.officer_totals : null
+  const officerNames = [...new Set([...(officerTotals ? Object.keys(officerTotals) : []), ...officers])].sort()
+  const filtered = Boolean(tierFilter || paymentFilter || dcFilter || productFilter || urlQ)
+  const filterDefs = [
+    { key: 'tier', label: t('today.tiers'), value: tierFilter,
+      options: tiers.map((tier) => ({
+        value: tier,
+        label: tierCounts && Number.isInteger(tierCounts[tier])
+          ? t('today.filter.tierOption', { tier: t(`tier.${tier}`), n: tierCounts[tier] })
+          : t(`tier.${tier}`),
+      })) },
+    { key: 'officer', label: t('today.officer'), value: officer, emptyLabel: t('today.allOfficers'), id: OFFICER_FILTER_ID,
+      options: officerNames.map((o) => ({
+        value: o,
+        label: officerTotals && Number.isInteger(officerTotals[o]) ? t('today.workloadRow', { officer: o, n: officerTotals[o] }) : o,
+      })) },
+    { key: 'payment_status', label: t('book.filter.payment_status'), value: paymentFilter,
+      options: TODAY_PAYMENT_STATUSES.map((code) => ({ value: code, label: t(`status.${code}`) })) },
+    { key: 'dc_status', label: t('book.filter.dc_status'), value: dcFilter,
+      options: (dcStatus.values || []).filter((v) => v.active !== false).map((v) => ({ value: v.code, label: labels.dc(v.code) })) },
+    { key: 'product', label: t('book.filter.product'), value: productFilter,
+      options: TODAY_PRODUCTS.map((code) => ({ value: code, label: t(`book.product.${code}`) })) },
+  ]
 
   // Feedback Round 1, WP7 / design F10 (a): every standing notice on this desk folds
   // into ONE "หมายเหตุระบบ (n)" at the end of the header. Nothing is deleted — the
@@ -639,13 +606,29 @@
       {role === 'OFFICER' && !officer && (
         <p className="td-pick" data-testid="pick-officer">
           <span>{t('today.pickOfficer')}</span>
-          <button type="button" className="btn btn--sm" onClick={() => officerSelect.current && officerSelect.current.focus()}>
+          <button type="button" className="btn btn--sm" onClick={() => document.getElementById(OFFICER_FILTER_ID)?.focus()}>
             {t('today.pickOfficerGo')}
           </button>
         </p>
       )}
       {od04Block}
       {cf1Block}
+      {/* Round-3 J3-04 / round-4 J4-09: an answer waiting on a case that ranks in a
+          higher tier is counted in THAT tier; said here, with a jump to the row that
+          holds it (list view — the board has no rows to jump to). */}
+      {answersElsewhere > 0 && (
+        <p className="td-quiet">
+          {t('tier.ANSWER_WAITING')}{' · '}
+          {view === 'board' || !firstWaitingUid ? (
+            <span data-testid="answers-elsewhere">{t('today.answersElsewhere', { n: answersElsewhere })}</span>
+          ) : (
+            <a className="td-tier__jump" href={`#td-waiting-${firstWaitingUid}`} data-testid="answers-elsewhere-go">
+              <span data-testid="answers-elsewhere">{t('today.answersElsewhere', { n: answersElsewhere })}</span>
+              {' · '}{t('today.answersElsewhereGo')}
+            </a>
+          )}
+        </p>
+      )}
       {/* R1-C05 / J3-14: why โทร and LINE are off, once for the list, with how many rows
           it covers. List view only (ruling 50: the board draws no dial control). */}
       {view === 'list' && (noPhoneRows > 0 || noLineRows > 0) && (
@@ -671,6 +654,10 @@
       {/* The badge, this header and the work book count different things; said once. */}
       <p className="td-quiet" data-testid="count-note">{t('today.countNote')}</p>
       {meta.counts_note_th && <p className="td-quiet" data-testid="counts-note-api">{meta.counts_note_th}</p>}
+      {/* B2: what the officer options' numbers are — served with them. */}
+      {officerTotals && meta.officer_totals_note_th && (
+        <p className="td-quiet" data-testid="officer-totals-note">{meta.officer_totals_note_th}</p>
+      )}
     </SystemNotes>
   )
 
@@ -690,6 +677,7 @@
             {' · '}{shownOfficer
               ? <span data-testid="officer-total">{t('today.officerTotal', { officer: shownOfficer, n: meta.total ?? items.length })}</span>
               : <span data-testid="team-total">{t('today.teamTotal', { n: meta.total ?? items.length })}</span>}
+            {filtered && <> · <span className="td-quiet" data-testid="today-filtered">{t('today.filter.on')}</span></>}
             {stale && <> · <span className="td-quiet" data-testid="today-loading">{t('today.loading')}</span></>}
           </p>
           {/* Ruling 66: which of the two representations of this desk the officer is
@@ -728,12 +716,6 @@
                        ]}
                        onChange={chooseDensity} />
           )}
-          <label className="td-quiet" htmlFor="td-officer">{t('today.officer')}</label>
-          <select id="td-officer" className="td-select" value={officer} onChange={(e) => chooseOfficer(e.target.value)}
-                  data-role={role} ref={officerSelect}>
-            <option value="">{t('today.allOfficers')}</option>
-            {officers.map((o) => <option key={o} value={o}>{o}</option>)}
-          </select>
           {/* Feedback Round 1, WP7 / F11: the reminder batch has its own page until the
               calendar takes it in; this is the one way to it from the desk. */}
           <Link className="btn btn--sm" to="/reminders" data-testid="today-reminders-link">{t('today.remindersLink')}</Link>
@@ -741,6 +723,9 @@
         </div>
       </header>
 
+      {/* B2: the bar sits above the work in both views; a filtered board shows
+          filtered cards, because the items themselves are filtered by the server. */}
+      <FilterBar filters={filterDefs} onChange={onFilter} search={q} onSearch={setQ} />
       {systemNotes}
       <LiveNotice tone="quiet" value={flash} onDismiss={() => setFlash(null)} />
       {problem && <Problem problem={problem} />}
@@ -880,8 +865,6 @@
             </Notice>
           )}
 
-          {tiersBlock}
-          {workloadBlock}
 
           {tiers.map((tier) => {
             // Only this page's rows. `onPage` is the window over the tier-ordered
@@ -1021,8 +1004,6 @@
               <span data-testid="no-next-up">{t('today.noNextUp')}</span>
             </Notice>
           )}
-          {tiersBlock}
-          {workloadBlock}
         </>
       )}
 
```

What the patch does, so a reviewer can check it without the file open:
- constants after `KEY_TODAY_VIEW`; `FilterBar` import;
- filter values read from `params`, the debounced search written back with `setParams(next, { replace: true })`;
- the load call builds `query` from the set filters and its `useCallback` deps gain the five filter values;
- `workload`, `workloadBusy`, the lead effect, `loadWorkload`, `officerSelect`, `tiersBlock`, `workloadBlock` and the `<label>`/`<select id="td-officer">` are removed;
- `onFilter(key, value)` after `chooseOfficer`; the early return wraps the `Problem` with the reset link on `validation_failed`;
- `filterDefs` (built after the early returns, no hooks) and the `FilterBar` mount after `</header>`;
- the pick-officer button focuses `document.getElementById(OFFICER_FILTER_ID)`;
- `systemNotes` gains the answers-elsewhere note and the officer-totals note; the sub line gains `today-filtered`.

`frontend/src/i18n-today.js`: after B1's `  'today.remindersPage.sub': …` line in `TODAY_EN` add

```js
  // Feedback Round 1, WP7 (B2): the filter bar.
  'today.filter.tierOption': '{tier} · {n}',
  'today.filter.on': 'filtered',
  'today.filter.reset': 'Show the unfiltered desk',
```

and after B1's `  'today.remindersPage.sub': …` line in `TODAY_TH` add

```js
  // Feedback Round 1, WP7 (B2): แถบตัวกรอง
  'today.filter.tierOption': '{tier} · {n} ราย',
  'today.filter.on': 'กรองอยู่',
  'today.filter.reset': 'แสดงรายการทั้งหมดโดยไม่กรอง',
```

- [ ] **Step 7: Run the Today tests and see exactly the eight pins fail**

Run: `npx vitest run src/screens/Today.test.jsx src/round4.test.jsx src/screens/Today.filter.test.jsx src/screens/Today.notes.test.jsx src/screens/Today.board.test.jsx src/screens/Reminders.test.jsx src/screens/WorkBook.test.jsx src/screens/Payments.test.jsx src/i18n.test.js src/today-density.test.jsx`
Expected (measured): 8 failed — the eight named under **Pins** — and every other test passes, including all 11 in `Today.filter.test.jsx`. If any other test fails, stop: that is a defect, not a pin.

- [ ] **Step 8: Spend edit 37**

Apply to the two test files as B1 left them (produced from, and verified against, that state):

```diff
--- a/frontend/src/screens/Today.test.jsx
+++ b/frontend/src/screens/Today.test.jsx
@@ -192,15 +192,21 @@
     expect(screen.queryByTestId('today-pager')).toBeNull()
   })
 
+  // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+  // the seven `.td-tier` chips (`data-tier-code`, `.td-tier__count[data-count]`, a
+  // TierChip) → the tier filter's seven options (`data-value`, the served
+  // `meta.tier_counts` in the label, the tier's name in words). The tier strip became
+  // Today's FilterBar (design WP7, B2). The queue-group order assertion is unchanged.
   it('renders the seven tiers in the API order with their counts', async () => {
-    const { container } = renderIn('th', <Today />)
-    await waitFor(() => expect(container.querySelectorAll('.td-tier').length).toBe(7))
-    const chips = [...container.querySelectorAll('.td-tier')]
-    expect(chips.map((c) => c.getAttribute('data-tier-code'))).toEqual(TIERS)
-    expect(chips.map((c) => c.querySelector('.td-tier__count').getAttribute('data-count')))
-      .toEqual(['0', '1', '1', '0', '0', '1', '0'])
-    // The tier is named in words, never a bare number (TierChip).
-    expect(chips[0].querySelector('.tier')).toHaveAttribute('data-tier', '1')
+    api.today.mockResolvedValue({ ...RESPONSE, meta: { ...RESPONSE.meta, tier_counts: RESPONSE.meta.counts_by_tier } })
+    const { container } = renderIn('th', <Today />)
+    fireEvent.click(await screen.findByTestId('filter-tier'))
+    const chips = within(screen.getByRole('listbox')).getAllByRole('option').slice(1)
+    expect(chips.map((c) => c.getAttribute('data-value'))).toEqual(TIERS)
+    expect(chips.map((c) => c.textContent.split(' · ')[1]))
+      .toEqual(['0 ราย', '1 ราย', '1 ราย', '0 ราย', '0 ราย', '1 ราย', '0 ราย'])
+    // The tier is named in words, never a bare number.
+    expect(chips[0]).toHaveTextContent('PTP ถึงกำหนดวันนี้')
     // The queue groups follow the same order.
     const groups = [...container.querySelectorAll('.td-group')].map((g) => g.id)
     expect(groups).toEqual(TIERS.map((tier) => `td-tier-${tier}`))
@@ -263,9 +269,14 @@
     renderIn('th', <Today entry="/?officer=noon" />)
     await screen.findByRole('region', { name: 'รายต่อไป' })
     expect(api.today).toHaveBeenCalledWith({ officer: 'noon' })
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // the native <select>'s value and its <option> values → the officer filter's
+    // trigger `data-value` and its options' `data-value`s, read with the list open.
+    // The officer select became the FilterBar's officer filter (design WP7, B2).
     const select = screen.getByLabelText('แสดงงานของ')
-    expect(select).toHaveValue('noon')
-    const names = [...select.querySelectorAll('option')].map((o) => o.value)
+    expect(select).toHaveAttribute('data-value', 'noon')
+    fireEvent.click(select)
+    const names = within(screen.getByRole('listbox')).getAllByRole('option').map((o) => o.getAttribute('data-value'))
     expect(names).toEqual(['', 'nantapol', 'noon', 'ploy'])
   })
 
@@ -414,7 +425,9 @@
     expect(api.today).toHaveBeenCalledWith({ officer: 'thip' })
     expect(screen.getByTestId('officer-total')).toHaveTextContent('thip · 3 ราย')
     expect(screen.queryByTestId('pick-officer')).toBeNull()
-    expect(screen.getByLabelText('แสดงงานของ')).toHaveValue('thip')
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // toHaveValue('thip') on the <select> → the officer filter's data-value (design WP7, B2).
+    expect(screen.getByLabelText('แสดงงานของ')).toHaveAttribute('data-value', 'thip')
     expect(screen.getByTestId('count-note')).toHaveTextContent('ป้ายที่เมนู "วันนี้" นับเฉพาะงานที่ถึงกำหนด')
   })
 
@@ -422,7 +435,11 @@
     renderIn('th', <Today />)
     await screen.findByRole('region', { name: 'รายต่อไป' })
     expect(api.today).toHaveBeenLastCalledWith({ officer: 'nantapol' })
-    fireEvent.change(screen.getByLabelText('แสดงงานของ'), { target: { value: 'ploy' } })
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // a change event on the <select> → opening the officer filter and picking the
+    // option, which is how its list is operated (design WP7, B2).
+    fireEvent.click(screen.getByLabelText('แสดงงานของ'))
+    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'ploy' }))
     await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'ploy' }))
     expect(screen.getByTestId('officer-total')).toHaveTextContent('ploy · 3 ราย')
     // The top bar changes: it wins again over the page override.
@@ -458,7 +475,9 @@
 
   it('prints tier_reason_th on the card and counts the รอคำตอบ chip from the partition (J3-04)', async () => {
     const items = RESPONSE.items.map((it) => it.customer.uid === 'cu-1' ? { ...it, tier_reason_th: 'งานถัดไปถึงกำหนดวันนี้ (โทรกลับ 09/06)' } : it)
-    api.today.mockResolvedValue({ ...RESPONSE, items, meta: { ...RESPONSE.meta, answers_waiting: 2 } })
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // the fixture gains the served `tier_counts` the tier filter reads (design WP7, B2).
+    api.today.mockResolvedValue({ ...RESPONSE, items, meta: { ...RESPONSE.meta, answers_waiting: 2, tier_counts: RESPONSE.meta.counts_by_tier } })
     const { container } = renderIn('th', <Today />)
     const hero = await screen.findByRole('region', { name: 'รายต่อไป' })
     expect(within(hero).getByTestId('tier-reason')).toHaveTextContent('งานถัดไปถึงกำหนดวันนี้')
@@ -471,21 +490,30 @@
     expect(screen.getByTestId('tier-reason-cu-1')).toBeInTheDocument()
     // Round-3 J3-04: the chip counts the rows IN the tier, so the chips add up to
     // meta.total; the answer that sits on a higher-tier case is said separately.
-    expect(container.querySelector('.td-tier[data-tier-code="ANSWER_WAITING"] .td-tier__count')).toHaveAttribute('data-count', '1')
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // the ANSWER_WAITING chip's data-count → the ANSWER_WAITING option's label (design WP7, B2).
+    fireEvent.click(screen.getByTestId('filter-tier'))
+    expect(within(screen.getByRole('listbox')).getByRole('option', { name: 'รอคำตอบ · 1 ราย' })).toHaveAttribute('data-value', 'ANSWER_WAITING')
     expect(screen.getByTestId('answers-elsewhere')).toHaveTextContent('รวมอยู่ในขั้นอื่น 1')
   })
 
   it('J3-04: the tier chips sum to meta.total and no chip stands over an empty section', async () => {
-    api.today.mockResolvedValue({ ...RESPONSE, meta: { ...RESPONSE.meta, answers_waiting: 2,
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // the seven chips' data-count → the tier filter's seven option labels, from the
+    // served `tier_counts` the fixture now carries (design WP7, B2). The two sums and
+    // the per-section comparison are unchanged.
+    api.today.mockResolvedValue({ ...RESPONSE, meta: { ...RESPONSE.meta, answers_waiting: 2, tier_counts: RESPONSE.meta.counts_by_tier,
       counts_note_th: 'คำตอบ 1 รายการอยู่บนเคสที่จัดอยู่ในขั้นสูงกว่า' } })
     const { container } = renderIn('th', <Today />)
     await screen.findAllByText('ลูกค้าทดสอบ 0187')
-    const counts = [...container.querySelectorAll('.td-tier__count')].map((el) => Number(el.getAttribute('data-count')))
+    fireEvent.click(screen.getByTestId('filter-tier'))
+    const optionCount = (tier) => Number(within(screen.getByRole('listbox')).getAllByRole('option')
+      .find((o) => o.getAttribute('data-value') === tier).textContent.match(/(\d+) ราย$/)[1])
+    const counts = TIERS.map(optionCount)
     expect(counts.reduce((a, b) => a + b, 0)).toBe(3)
     for (const tier of TIERS) {
-      const chip = container.querySelector(`.td-tier[data-tier-code="${tier}"] .td-tier__count`)
       const rows = container.querySelectorAll(`#td-tier-${tier} tbody tr[data-uid]`)
-      expect(Number(chip.getAttribute('data-count')), tier).toBe(rows.length)
+      expect(optionCount(tier), tier).toBe(rows.length)
     }
     // The API's own sentence about the two numbers is on the screen, not only in JSON.
     expect(screen.getByTestId('counts-note-api')).toHaveTextContent('ขั้นสูงกว่า')
--- a/frontend/src/round4.test.jsx
+++ b/frontend/src/round4.test.jsx
@@ -655,14 +655,23 @@
     setRole('MANAGER')
     setRoster([{ uid: 'nantapol', display_name_th: 'นันทพล', role: 'OFFICER' },
                { uid: 'thip', display_name_th: 'ทิพย์', role: 'OFFICER' }])
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // one /v1/today call per officer, each read back as a "thip · 74 ราย" button in the
+    // team-workload panel → ONE response serving `meta.officer_totals`, read back as the
+    // officer filter's options, and picking one filters the desk to it. The panel became
+    // the FilterBar's officer filter (design WP7, B2).
     api.today.mockImplementation((params) => Promise.resolve(TODAY({
-      meta: { total: params?.officer === 'thip' ? 74 : 63, next_up: 'cu-1', tiers: [], counts_by_tier: {} },
+      meta: { total: params?.officer === 'thip' ? 74 : 63, next_up: 'cu-1', tiers: [], counts_by_tier: {},
+              officer_totals: { nantapol: 63, thip: 74 } },
     })))
     renderIn('th', <Today />)
     // Round-5 J5-11 (second round): the lead's one cross-desk number now loads with
     // the page. Pressing a button to reveal it was the thing that never worked.
-    expect(await screen.findByRole('button', { name: 'thip · 74 ราย' })).toBeInTheDocument()
-    expect(screen.getByRole('button', { name: 'nantapol · 63 ราย' })).toBeInTheDocument()
+    fireEvent.click(await screen.findByTestId('filter-officer'))
+    expect(await screen.findByRole('option', { name: 'thip · 74 ราย' })).toBeInTheDocument()
+    expect(screen.getByRole('option', { name: 'nantapol · 63 ราย' })).toBeInTheDocument()
+    fireEvent.click(screen.getByRole('option', { name: 'thip · 74 ราย' }))
+    await waitFor(() => expect(api.today).toHaveBeenLastCalledWith({ officer: 'thip' }))
   })
 
   it('the assignment select on /settings offers the roster the API names', async () => {
@@ -760,7 +769,11 @@
     setRole('MANAGER')
     renderIn('th', <MemoryRouter><TodayScreen /></MemoryRouter>)
     await screen.findByTestId('team-total')
-    fireEvent.change(screen.getByLabelText('แสดงงานของ'), { target: { value: 'thip' } })
+    // AUTHORISED TEST EDIT 37 (Feedback Round 1 plan, Arina's approval 2026-09-15):
+    // a change event on the officer <select> → opening the officer filter and picking
+    // "thip" (design WP7, B2).
+    fireEvent.click(screen.getByLabelText('แสดงงานของ'))
+    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'thip' }))
     // While thip's list is in flight the header must not claim thip has 63.
     await screen.findByTestId('today-loading')
     expect(screen.queryByTestId('officer-total')).toBeNull()
```

- [ ] **Step 9: Run the focused tests, the suite and the census**

Run: the Step 7 command again.
Expected (measured): 10 files, 0 failed (`Today.test.jsx` 31, `round4.test.jsx` 44, `Today.filter.test.jsx` 11).

Run: `npx vitest run 2>&1 | tail -4`
Expected: Step 1's count **+ 1 file, + 11 tests** (measured on a scratch copy after B1, B3 and B2b: 69 files, 755 tests over the 63 / 726 `caddc4b` baseline). Paste it.

Run: `npx vitest run src/today-density.test.jsx 2>&1 | grep TODAY`
Expected (measured): `TODAY  chrome=104  perRow=31  at 50 rows=1654` and `visible=1654`. Paste both.

Then `./scripts/verify_all.sh` from the repo root: EVERYTHING PASSED, e2e 31 of 31 (`e2e_check.py` calls `/v1/today` without parameters, and B2a keeps that call unchanged).

- [ ] **Step 10: Commit**

```bash
MSG=$(mktemp)
cat > "$MSG" <<'EOF'
feat(today): one filter bar — tier, officer with each desk's served total, payment status, DC status, product and search

Design WP7 (B2). The tier strip, the officer select and the "whole team today" panel
become the Work Book's FilterBar above the list and the board. The filters live in the
URL, travel to /v1/today only when set, and every number an option prints is served
(meta.tier_counts, meta.officer_totals): the panel's one call per officer and its
client-side total are gone. The answer waiting on a higher tier moves into the
หมายเหตุระบบ fold with its jump.

AUTHORISED TEST EDIT 37: eight pinned tests read the chips, the <select> or the panel's
buttons; they now read the filter options (Today.test.jsx:196-203, :266-269, :445,
:453, :490, :503, :508-509, :512-518; round4.test.jsx:661-663, :667-668, :766).
Today density: chrome 105 -> 104, per row 31, page 1,655 -> 1,654.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/screens/Today.filter.test.jsx
git commit -F "$MSG" -- frontend/src/screens/Today.filter.test.jsx frontend/src/components/SearchSelect.jsx frontend/src/components/FilterBar.jsx frontend/src/screens/Today.jsx frontend/src/i18n-today.js frontend/src/screens/Today.test.jsx frontend/src/round4.test.jsx
```

---

### Task B4: The Today density measure

**Files:**
- Read: `frontend/src/today-density.test.jsx` (no edit)
- Scratch only (never committed): a copy of `frontend/src` with one extra census file, `zz-b4.test.jsx`

**Interfaces:**
- Consumes: the committed state after B1, B3, B2a and B2b; `today-density.test.jsx`'s `visibleIn` method (elements inside a shut `<details>`, except its `<summary>`, are hidden; only the outermost shut fold counts).
- Produces: six census lines for the controller's ledger. No product or test file changes.

**Pins:** 0. Caps stay 31 / 112 / 1,662 (controller ruling). A ratchet may only be lowered by a numbered edit, and none is asked for here.

**Why a scratch fixture as well:** `today-density.test.jsx`'s fixture serves no `tier_counts`, `officer_totals`, `officer_totals_note_th`, `counts_note_th`, `ptp_history_note_th` or waiting answer, and never sets a filter, so on its own it does not measure the `today-filtered` mark or a lead's view. B4 serves them in a scratch copy.

- [ ] **Step 1: The ratchet, as committed**

Run (from `frontend/`): `git log --oneline -6` (B1, B3, B2a, B2b present), then `npx vitest run src/today-density.test.jsx 2>&1 | grep -E "TODAY|Tests"`
Expected (measured): `TODAY  chrome=104  perRow=31  at 50 rows=1654 …`, `TODAY  full page (50 rows) visible=1654`, `TODAY  row cells: name=5  td-table__next=5  td-table__num=3  td-table__dpd=3  name=2  td-table__act=5  total=29`, `TODAY  per row: all=31 tr=2 option=0 li=0 a=1`, 5 passed. If chrome > 112, per row > 31 or page > 1,662, stop and report: a later task in another cluster (P2's B7 dial buttons, P3's B12 greeting) has spent elements, and the cut or the numbered edit is the controller's.

- [ ] **Step 2: Build the scratch copy**

Run (from the repo root; `<scratch>` is your session scratchpad):

```bash
mkdir -p <scratch>/b4 && cp -R frontend/src <scratch>/b4/src && cp frontend/vite.config.js frontend/package.json <scratch>/b4/ && ln -s /Users/parattakorn/volt-debt-prototype/frontend/node_modules <scratch>/b4/node_modules
```

- [ ] **Step 3: Write the served-extras census into the copy**

`<scratch>/b4/src/zz-b4.test.jsx`:

```jsx
// P1 scratch (B4): today-density.test.jsx's own census, re-run on fixtures that SERVE
// what B1-B3 added — the filter counts, the officer totals and their note, the API's
// count note, the PTP-history note, one waiting answer elsewhere, a filter set in the
// URL — as an OFFICER and as a MANAGER on "everyone".
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from './test-utils.jsx'
import { api } from './api.js'
import { setOfficer, setRole, setRoster } from './components/role.jsx'
import TodayScreen from './screens/Today.jsx'

vi.mock('./api.js', () => ({
  api: {
    today: vi.fn(), todayItemDone: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(),
    dictionary: vi.fn(), logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(),
  },
}))

const TIERS = ['PTP_DUE_TODAY', 'NEXT_ACTION_DUE', 'BROKEN_PTP', 'AT_RISK_TWO_MISSED',
               'NEW_ARREARS', 'ANSWER_WAITING', 'ROUTINE']
const CASE = (over = {}) => ({
  uid: 'case-1', payment_status: 'LATE', dc_status: null, npl_type: null,
  next_action: 'CALLBACK', next_action_on: '2026-06-09', next_action_set_by: 'MAPLOG_IMPORT',
  last_contact_at: '2026-06-11 13:39:42', last_contact_by: 'thip', last_result: 'UNREACHABLE_NO_ANSWER',
  broken_ptp_count: 0, kept_ptp_count: 0, renegotiation_count: 0, power_state: 'ON', review_uid: null,
  open_ptp: null, open_issue: null,
  sheet: { days_late: null, late_fees: null, overdue: null, bucket: '<90 days', payment_status: 'Late',
           dc_status_raw: null, npl_type_raw: '', comment_th: null, comment_en: null, source_refs: [[44, 31]] },
  volt_id: '99999000112_Kun_VOLT', officer_uid: 'nantapol',
  ...over,
})
const ITEM = (n) => ({
  customer: {
    uid: `cu-${n}`, customer_no: `2800504352${n}`, display_name: `ลูกค้า ทดสอบ ${n}`,
    phone_masked: '08x-xxx-8720', phone_e164: null, line_id: null, contract_count: 1, officer: 'nantapol',
  },
  entity: 'SPV', company_id: 'CO-SPV',
  aggregate_overdue: '2999.00', aggregate_outstanding: '212928.99',
  oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL', fee_state: null,
  open_ptp: null, broken_ptp_count: 0,
  contact_lock: { state: 'OPEN', locked_by: null, locked_at: null },
  session_last_contact: null, ladder: null,
  tier: 'ROUTINE', tier_rank: 7, priority_reason: 'ROUTINE',
  waiting: [], missed_count: 1,
  case: CASE({ uid: `case-${n}` }),
})
const response = (rows) => ({
  run: { business_date: '2026-10-23', job: 'today', officer: null, ordering: 'tiers' },
  items: Array.from({ length: rows }, (_, i) => ITEM(i + 1)),
  meta: {
    total: rows, next_up: 'cu-1', tiers: TIERS,
    counts_by_tier: { PTP_DUE_TODAY: 0, NEXT_ACTION_DUE: 0, BROKEN_PTP: 0,
                      AT_RISK_TWO_MISSED: 0, NEW_ARREARS: 0, ANSWER_WAITING: 0, ROUTINE: rows },
    tier_counts: { PTP_DUE_TODAY: 1, NEXT_ACTION_DUE: 0, BROKEN_PTP: 9, AT_RISK_TWO_MISSED: 68,
                   NEW_ARREARS: 1, ANSWER_WAITING: 0, ROUTINE: rows },
    officer_totals: { nantapol: 63, noon: 7, ops: 0, owner: 0, ploy: 7, settasak: 0, thip: 74 },
    officer_totals_note_th: 'จำนวนรายการในลิสต์วันนี้ของเจ้าหน้าที่แต่ละคน ไม่ขึ้นกับตัวกรองอื่น',
    counts_note_th: 'ชิปแต่ละขั้นรวมกันได้เท่ากับจำนวนรายการทั้งหมด',
    ptp_history_note_th: 'ยังไม่มีนัดที่บันทึกว่าชำระตามนัดในระบบ',
    answers_waiting: 1, answers_waiting_elsewhere: 1,
  },
})

function visibleIn(el) {
  const closed = [...el.querySelectorAll('details')].filter((d) => !d.hasAttribute('open'))
  const outermost = closed.filter((d) => !closed.some((o) => o !== d && o.contains(d)))
  const hidden = outermost.reduce((n, d) => {
    const summary = d.querySelector(':scope > summary')
    return n + d.querySelectorAll('*').length - (summary ? summary.querySelectorAll('*').length + 1 : 0)
  }, 0)
  return el.querySelectorAll('*').length - hidden
}

async function mount(rows, entry) {
  api.today.mockResolvedValue(response(rows))
  api.reminders.mockResolvedValue({ items: [], meta: {} })
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  const view = renderIn('th', <MemoryRouter initialEntries={[entry]}><TodayScreen /></MemoryRouter>)
  await screen.findByRole('heading', { level: 1 })
  return view
}

async function census(label, entry) {
  const { container: a, unmount } = await mount(1, entry)
  const one = visibleIn(a)
  unmount()
  const { container: b, unmount: u2 } = await mount(11, entry)
  const eleven = visibleIn(b)
  u2()
  const perRow = Math.round((eleven - one) / 10)
  const { container: c } = await mount(50, entry)
  const page = visibleIn(c)
  // eslint-disable-next-line no-console
  console.log(`B4 ${label}  chrome=${one - perRow}  perRow=${perRow}  page50=${page}`)
  return { chrome: one - perRow, perRow, page }
}

beforeEach(() => { vi.clearAllMocks(); setRoster([]) })

describe('B4 scratch census', () => {
  it('OFFICER, served extras, unfiltered', async () => {
    setRole('OFFICER'); setOfficer('nantapol')
    const r = await census('officer-served', '/')
    expect(r.chrome).toBeGreaterThan(0)
  })
  it('OFFICER, served extras, a tier filter set', async () => {
    setRole('OFFICER'); setOfficer('nantapol')
    const r = await census('officer-filtered', '/?tier=ROUTINE')
    expect(r.chrome).toBeGreaterThan(0)
  })
  it('MANAGER on everyone, served extras', async () => {
    setRole('MANAGER'); setOfficer('settasak')
    const r = await census('manager-everyone', '/')
    expect(r.chrome).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 4: Run it**

Run: `frontend/node_modules/.bin/vitest run --root <scratch>/b4 src/zz-b4.test.jsx 2>&1 | grep "^B4 "`
Expected (measured on a scratch copy after B1, B3 and B2b):

```
B4 officer-served  chrome=104  perRow=31  page50=1654
B4 officer-filtered  chrome=105  perRow=31  page50=1655
B4 manager-everyone  chrome=105  perRow=32  page50=1705
```

For the ledger, the same file at HEAD measured `114 / 31 / 1664`, `114 / 31 / 1664` and `119 / 32 / 1719`: WP7 gives back 10 elements on an officer's desk and 14 on a lead's. The MANAGER row's per-row 32 and page 1,705 are the pre-existing officer name every row shows in "ทุกคน" mode (`QueueRow` `showOfficer`, HEAD `:1271`), present at HEAD too; the committed ratchet measures OFFICER and is not changed.

- [ ] **Step 5: Report, no commit**

Paste the Step 1 lines and the Step 4 lines into the task report. Nothing is committed; delete `<scratch>/b4` when done.

---

## Self-review (WP7)

**How this section was checked.** Every code block above was built and run before it was written down, on scratch copies outside the worktree (`frontend/src` and `backend/` copied at `b5bdc7c`; the worktree was never modified):
- Frontend after B1 + B3 + B2b: **71 files / 759 tests passed**, of which 2 files / 4 tests were scratch probes, so **69 / 755** for this section over the `caddc4b` 63 / 726.
- Backend after B2a: **1,040 passed / 11 skipped**, 0 failed (the copy carried another session's uncommitted PEAK/attachment work, so the absolute number is not the branch's; the delta is +13).
- `test_today_filters.py` against unmodified HEAD: all 13 fail, for the reasons Step 3 of B2a names.
- The B2a, B2b-components patches pass `git apply --check` on HEAD. The B2b `Today.jsx` and edit-37 patches pass `patch --dry-run` on reconstructions of the post-B3 / post-B1 files. The post-B3 reconstruction itself passes the density, `Today.notes`, `Today.board`, `Reminders` and `SystemNotes` tests at chrome 105.

**Spec coverage — design §3 WP7, line by line.**

| WP7 text | where |
|---|---|
| "The reminders block leaves Today (list and board)" | B1 Step 6 items 3–9 (both mounts); tests "draws no reminder block in list view…" and "…in board view either" |
| "Until WP6 lands it lives on `/reminders`, same component, same test ids (F11)" | B1 Step 5 (`Reminders.jsx`), Step 6 (route, `SUB_PAGES`); the three pinned tests run unchanged against it (edit 36) |
| "The tier strip and 'Whole team today' become a FilterBar above the list, the exact component Work Book uses" | B2b (the same `FilterBar`/`SearchSelect`; two additive props) |
| "ระดับ (the seven tiers, counts in the option labels)" | B2a `meta.tier_counts`; B2b tier filter; tests "labels the tier options with the served tier_counts…" and `test_the_tier_filter_narrows_the_desk…` |
| "เจ้าหน้าที่ (roster with today's counts — this is the team-workload data)" | B2a `meta.officer_totals` (= each officer's `/v1/today` total, proved per officer); B2b officer filter. Label kept "แสดงงานของ" (deviation 5) |
| "สถานะการชำระ, สถานะติดตาม, ผลิตภัณฑ์, plus the search box" | B2a params + validation; B2b filters. Labels reuse the Work Book's words ("สถานะชำระ", "สถานะ DC", "ผลิตภัณฑ์") so the two bars read the same |
| "The board keeps the same bar; a filtered board shows filtered cards" | B2b mounts the bar outside the view branch; the server filters `items`; test "the board keeps the same bar…" |
| Brief: "`GET /v1/today` filters that refuse unknown values" | B2a `_valid_choice`, 422 with `known`, before any row is built |
| "The standing notices fold into one line: OD-04 indicative, CF1 …, 'call is off on n rows', the PTP-history note and 'pick an officer' … a single `<details>` 'หมายเหตุระบบ (n)' at the end of the header" | B3 `SystemNotes` + Today's `systemNotes`, right after `</header>`; test "the fold sits between the header and the work". "CF1 reminder offsets": the offsets-conflict line leaves Today with its batch (B1) and stays inside that batch on `/reminders`; the CF1 penalty band (`refusal-cf1`) folds (B3) |
| "The refusals stay reachable" | children always rendered in a native `<details>` (no `hidden`), ids kept; test "the column marks still point at the folded bands by id" |
| "Recovery.jsx's eight and InvoicePipeline.jsx's one notice get the same fold" | B3 Step 7 (deviation 6 names the four per-case facts that stay on cards) |
| "`InvoicePipeline.test.jsx:102` pins one of them by role, so that one keeps its `role="status"` inside the fold" | B3 Step 7 keeps the `<Notice>`; new test asserts the fold contains `getByRole('status')` |
| "Density: … Measured before spending (§5)" | per-task census steps; B4 with served extras |

**Placeholder scan.** No "TBD", "TODO", "add validation" or "similar to Task N". The only placeholders are the two the brief defines or that name a caller-owned path: `<task-db>` (the controller's database) and `<scratch>` (the implementer's scratchpad in B4). Edit numbers 36 and 37 are concrete but are the controller's to confirm.

**Name consistency across this section's interfaces.**
- B2b reads exactly the keys B2a serves: `meta.tier_counts`, `meta.officer_totals`, `meta.officer_totals_note_th`; the 422 body B2b's reset link keys on is `code: "validation_failed"`, which `errors.validation_failed` sets.
- B2b's pick-officer button and B3's `systemNotes` meet at one line: B3 writes `officerSelect.current && officerSelect.current.focus()`, B2b's patch replaces it with `document.getElementById(OFFICER_FILTER_ID)?.focus()`.
- B2b's patch adds two notes inside B3's `systemNotes` (answers elsewhere, officer totals) and deletes `tiersBlock`/`workloadBlock`, whose mounts B3 left in place deliberately.
- `offsetsLabel` lives in `Reminders.jsx` and is re-exported by `Today.jsx`, so `Today.test.jsx:9` and `:474-480` are unaffected.
- `SUB_PAGES` in `Shell.jsx` uses `today.remindersPage.title`, the same key as the page `<h1>` and the `rememberOrigin` `screenKey`.
- P5 / C3 consumes `screens/Reminders.jsx`, `screens/Reminders.test.jsx`, the `/reminders` route in `App.jsx` and the `SUB_PAGES` entry — all named here with those paths.

**Assumptions not verified in the code or not verifiable here.**
1. **Screen readers and the shut fold.** jsdom exposes a `role="status"` inside a shut `<details>` to `getByRole`; a real browser removes shut content from the accessibility tree, so the pipeline's owner notice is no longer announced. `Notice.jsx:25-29` already says these static notices are not announcements. Not checked in a browser or screen reader.
2. **`aria-describedby` into a shut `<details>`.** The column marks point at bands inside the fold; the accname rules include hidden referenced content in a description. Not checked with a screen reader.
3. **Login mode and `X-Volt-Officer`.** B2a accepts the caller's own `X-Volt-Officer` identity as a known officer. It was not checked whether `AUTH_MODE` on rewrites that header from the session. P3's B10 invited accounts: a lead filtering to an invited officer who has no case and is not in `officers.registry()` gets a 422 until a case is assigned to them (their own desk works).
4. **Timing.** `/v1/today` measured 0.28 s unfiltered and 0.11 s for one officer at HEAD; `officer_totals` adds one pass over the 212 book customers without building work items. Not re-timed after the change. The search-box test relies on the real 250 ms debounce inside `waitFor`'s 1 s; it passed every run but could flake on a loaded machine.
5. **Layout.** Five `SearchSelect`s plus the search box on Today's header width, and the fold's look, were not checked in a browser (no Playwright run for this plan).
6. **Dead CSS left.** `.td-tiers`, `.td-tier` (except `.td-tier__jump` and `.td-tier__count`, still used), `.td-workload` and `.page-note` in `today.css` become unused; they are left to keep this section out of the `today.css` hotspot. No test checks unused rules.
7. **Other clusters' later edits.** The density margins (chrome 104 of 112, page 1,654 of 1,662) assume P2's B7 and P3's B12 measure their own additions; B4 Step 1 stops if they have spent past a cap.
8. **HEAD drift.** Measured at `b5bdc7c` with another session's uncommitted edits in the worktree (`guard.py`, `journey.py`, `routers/journey.py`, `PeakReportCard.jsx`). None is a WP7 file, but the absolute suite counts in this plan are scratch counts; each task re-measures.
9. **`verify_all.sh` (e2e) was not run** for this plan; `e2e_check.py:859,884,920` call `/v1/today` with no parameters, which B2a leaves unchanged.


<!-- ===== cluster section: P2-wp8-wp9.md ===== -->

# Round B — WP8 (case header, figures only) and WP9 (phone on the case) — planner P2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tasks:** B5 (WP8), B6 (WP9 backend), B7a (WP9 phone control), B7b (WP9 mounts). Note 11's B7 is split in two, each testable on its own.

**Goal:** The case header shows figures. Every explanation of a figure folds into one closed "รายละเอียดการคำนวณ" section next to the history fold, and the Owner gets a link to the settings behind the penalty. A person can store a real phone number per customer, with a reason. It is audited without the number. Every read serves it first, Today's dial buttons use it, and the case header and the Save-contact dialog show it with copy and edit.

**Authority:** design note 10 §3 WP8 and WP9, rulings F9 (a) and F12 (a) (approved 2026-09-15), F17 (edits 36–39, none spent here).

**Measured at:** HEAD `91b8519` (2026-09-15). The branch moved during planning, from `caddc4b` through `c7d2552`, `b5bdc7c` and `91b8519`. Those commits touched `backend/app/routers/journey.py` only at `record_receipt` (around line 1625). No line this plan anchors on moved. Re-check with `git log --oneline -8` before each task.

## Global constraints (every task below carries them)

- **Baseline to beat (at caddc4b):** backend 1,022 passed / 11 skipped, frontend 726 passed / 63 files, e2e 31 of 31 (`scripts/verify_all.sh`). HEAD has moved since then, so re-measure before starting.
- **Test contract:** a pinned (pre-existing) test changes only as a numbered edit 36–39. The edit is measured first and carries `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`. Adding tests is free. **This section spends no numbered edit.**
- **Density ratchets:**
  - `frontend/src/density.test.jsx` caps the case page at 109 pre-contact / 128 worked. Its fixtures carry a served `payment_summary` and a stale `payment_position`.
  - `frontend/src/today-density.test.jsx` caps Today at 31 per row, 112 chrome, 1,662 per 50-row page.
  - Every screen task measures before and after and pastes the census lines.
  - A density fixture that does not carry the block a task adds does not measure it, so the measure step serves the block in a scratch copy.
  - Controller ruling: the caps stay 109/128 and 31/112/1,662.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns. That includes sums across served rows.
- REQ-COL-075: `payment_status` keeps its five values. `payment_status` and `dc_status` stay two fields. `StatusPair` is not modified.
- PKD-001: `backend/app/integrations/peak.py` is not imported or edited.
- **Raw-body uploads only.** No `UploadFile` parameter (`python-multipart` is not installed).
- **Honesty:**
  - A configured-but-unreachable dependency refuses. An unconfigured one is labelled.
  - Every refusal is an RFC 9457 problem with `message_th`. In `routers/today.py`, `problem_from(exc)` fills `errors[0]` only when the CaseError carries `pointer=`.
  - Nothing falls back silently.
- **PDPA:**
  - A phone number is stored only in `records.customer_contact` and is never logged.
  - The audit detail carries `"set"`/`"cleared"`, never the number.
  - `AUTH_MODE` is never written into `backend/.env`. Test-account passwords are never printed.
- **Write routes:** role-gated where the design names a role, and audited with `audit.describe(act=…, subject=…, detail=…)` before any side effect that can raise. Sign with `who(body, x_volt_officer)`. `officers.sign` returns a TUPLE.
- **Strings:** user-facing text goes in `frontend/src/i18n-today.js`, which holds two FLAT objects, `TODAY_EN` and `TODAY_TH`. Before adding a key, grep all four tables for it: `grep -n "'case\.calc\|'case\.phone\." frontend/src/i18n-*.js`. At HEAD this returns nothing; `case.phoneAbsent` is a different key. `i18n.test.js` does not catch a same-table overwrite.
- **Python:** 3.9-safe (no `match`, no runtime `X | Y`).
- **CSS:** real tokens only (`--ink-*`, `--line-default`, `--caption-12`, `--label-13`, …). No `--space-*`, `--radius-*` or bare `--line`. Literal px for spacing, no hex.
- **Frontend patterns:**
  - Async work needs an unmount/`alive` guard.
  - A `vi.mock('../api.js')` object returns a Promise from every binding called at mount.
  - `rerender` re-wraps `PrefsProvider`.
  - Set the role with `setRole` from `components/role.jsx`.
  - Today mounts `CaseContactDrawer` with `key={drawerFor.customer.uid}`.
- **Worktree rules:**
  - Use `backend/.venv/bin/python` and run pytest without `-q`.
  - `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data`, where the controller assigns `<task-db>`.
  - Never set `DATABASE_URL` to `volt_local`. Never use a bare `git stash`. Never cd into `/Users/parattakorn/volt-debt-prototype`.
  - Commit with a message FILE plus a pathspec: `git add <new files>` then `git commit -F <file> -- <paths>`. The message ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W`.
  - Never `git add -A`.

## Shared files (exact touches, at HEAD 91b8519)

| File | Task | Exact touch | Other clusters |
|---|---|---|---|
| `backend/app/schema.sql` | B6 | Append one block after the last line (274, `attachment_target_idx`): `records.customer_contact` plus `customer_contact_active_idx`. | P3 appends `records.user_account` and P5 appends `records.notice` at the same tail. Whoever lands second appends after the first. |
| `backend/app/routers/today.py` | B6 | (1) line 9: `from .. import customer_contact` after `from .. import clock`. (2) lines 91–93: two rows in `problem_from`'s mapping after `attachment_unknown` (**claims error ids DEBT-COL-0463 and DEBT-COL-0464**). (3) line 694: the pre-install `customer` dict. (4) line 835: `case_detail`'s top-level `customer` dict. (5) a new route inserted before line 1063 (`/npl-type`), after `set_payment_status`. | P1 edits `today()` (147–153) and `_workbook` filters; P5 may add CaseError rows to the same mapping and must take ids from 0465. |
| `backend/app/routers/journey.py` | B6 | line 13 (import); lines 210–217 (`_work_item`'s customer dict: the three phone keys become one `**customer_contact.phone_fields(...)`). | — |
| `backend/app/cases.py` | — | **0 touches.** `set_phone` lives in the new `backend/app/customer_contact.py`. | P5 (notices) |
| `backend/tests/conftest.py` | B6 | One reset line after line 52 (`attachments_store.reset()`). | any cluster adding a memory store |
| `frontend/src/screens/CustomerCase.jsx` | B5, B7b | B5: imports lines 2 and 15; after 472 (`calcHas`); 609–631 (hold toggle out, `slot="face"`); 675–692 (ladder toggle out); after 1481 (the new fold section). B7b: import after 26; after `calcHas` (`savePhone`); 536–538 (phone span → `PhoneOnCase`); 576–577 (`why`); the drawer mount at 1855–1874 (`onPhoneSaved`). | — |
| `frontend/src/components/CaseContactDrawer.jsx` | B7b | line 16 (import), 254–255 (the `onPhoneSaved` prop), after 327 (`phoneServed` state), after 432 (reset), after 462 (`savePhone`, `shownCustomer`, `dialItem`), 900–903 (phone span → `PhoneOnCase`), 909 (`ContactActions item={dialItem}`). No restructuring. | P5's calendar may open the dialog; the new prop is optional. |
| `frontend/src/components/MoneyPosition.jsx` | B5 | the whole file (a new `slot` prop plus the exported `noteDisclosure`); default behaviour byte-identical. | — (Today and WorkBook call it without `slot`) |
| `frontend/src/api.js` | B7a | one binding after line 246 (`setPaymentStatus`). | P1, P3, P5 add bindings |
| `frontend/src/i18n-today.js` | B5, B7a | B5 adds 7 keys (`case.calc.*`); B7a adds 15 keys (`case.phone.*`). Appended at the end of `TODAY_EN` (before its `}` at line 610) and `TODAY_TH` (before line 1146). | P1 and P3 append at the same tail |
| `frontend/src/today.css` | B5, B7a | one rule each, after line 532 (`.cs-slip .btn`). | P1 (Today filter bar / notices) |
| `frontend/src/screens/Today.jsx` | — | **0 touches.** The dial buttons read the served `customer.phone_e164`: the hero `ContactActions` at 1206, the queue row at 1330 (`quietDial why={false}`), the board card at 1742 (`dial={false}`, no dial). `noPhoneRows` at 519 and `dial-disabled-why` at 985–989 count the served field. The drawer mount at 1164–1184 is unchanged (Today reloads on close). | P1 (FilterBar, notices fold), P3 (title) |
| `frontend/src/density.test.jsx`, `frontend/src/today-density.test.jsx` | — | **0 edits.** Measured only. | P1 (B4) |

## Depends on

- **Nothing blocks the build.** B6 (backend) and B5 (frontend) touch disjoint files and can run in parallel. B7a follows B6 so the served shape is real. B7b follows B5 and B7a: both edit `CustomerCase.jsx`, and on a real case B7b's cost is paid for by B5's give-back (see Density).
- **P3 / B9 (soft):** B5's Owner link goes to `/settings?field=late_payment_daily_rate` and `/settings?field=late_payment_grace_days`. That B9's form scrolls to or focuses `cfg-<key>` from `?field=` is **P3's to build**. Until it does, the link opens Settings at the top and nothing breaks. The interface is recorded here for P3: read `useSearchParams().get('field')`, scroll `[data-testid="cfg-<field>"]` into view, and focus its `cfg-edit-<field>` button when that button is shown.

## Who may read and who may write the number (F9 (a), PDPA)

- **Write:** any role that the API accepts (OFFICER, SUPERVISOR, MANAGER, OWNER, OPS). F9 (a) says "any officer"; this is read the same way `/dc-status` and `/payment-status` are ("any role"). A reason is required, and the write is audited as `PHONE_SET` with detail `{"phone": "set"|"cleared", "kind": "MOBILE"|"LANDLINE"|null, "reason": <the reason with any run of 9 or more digits cut out>}`.
- **Read, as served today (measured):**
  - `customer.phone_e164` goes to every role on `/v1/today`, `/v1/workbook`, `/v1/working-list` and `/v1/cases/by-customer/{uid}` (both `work_item.customer` and the top-level `customer`).
  - It is not in either CSV export: `_write_rows` in `routers/today.py:459` has no phone column.
  - It is not in the audit log. The middleware records no request or response bodies, and `CASE_VIEWED` carries only the subject uid.
  - With login on, only allow-listed sessions reach any of these.
- **B6 keeps that audience:**
  - It adds no reader, no export column and no event.
  - The number is in `records.customer_contact` only. It is never in an `app` session Store, never in `cs.events`, never in a `print`/log line, and never in an error message: a failed write re-raises by class name, unchained.
  - Staging is in Singapore (the PDPA flag stands, design §7).
  - The runtime-grants gap for schema `records` (note 10 §9.4) covers this table too.

## Density — measured (census method of `density.test.jsx`, OFFICER; OWNER is +1 everywhere at HEAD already)

The fixtures of `density.test.jsx` serve no `money_position`, no `ladder` and no `allocation_note_standing_th`. The seeded book serves all three on **212 of 212** cases (measured 2026-09-15 by walking `/v1/cases/by-customer/{uid}` for every workbook row). That means 11 always-visible header elements have never been counted. The scratch copy served those blocks and the phone override in the served shape B6 defines:

| State served (pre-contact / worked) | HEAD | after B5 | after B5 + B7b |
|---|---|---|---|
| `density.test.jsx` fixtures as they stand (+PAY) | **109 / 128** | **109 / 128** | **109 / 128** |
| same + a phone override | 110 / 129 | 110 / 129 | 113 / 132 |
| + `money_position`, `ladder`, `allocation_note_standing_th` (the real page) | 120 / 139 | 117 / 136 | 117 / 136 |
| real page + a phone override | 121 / 140 | 118 / 137 | 121 / 140 |

- **B5** takes three toggles out of the header: `arrears-hold-toggle` (2), the `mp-note-toggle` together with the `.mp` div that held only it (3), and `ladder-toggle` (2), for −7. It adds the fold (section, details, summary, h2) for +4. Net −3 on the real page and 0 on the fixture, because nothing it moves is in the fixture and the fold mounts only when there is something to explain.
- **B7b** adds the edit control (+1) on every case. On the case header it passes `why={Boolean(item?.customer?.phone_e164)}` to `ContactActions`, so the no-phone sentence drops (−1). That sentence is now said by the phone line beside the add control, and it has no pin on the case page (`Today.test.jsx:226` is the hero; `CaseContactDrawer.test.jsx:209` is `ContactActions` standalone). Net 0 on every case without a number. A case with a number gains the number, copy, edit, the sheet line and the dial link against the old mask span: +4 over the no-number state and +3 over HEAD's served-phone state.
- **Decision: no numbered edit.** The fixture census stays exactly 109/128. On the real page B5 + B7b are −3 without a number and ±0 with one. A phone override on the thin fixture would read 113/132, but that state does not exist on a real case, where the three header blocks are always served.
- **Flagged for the controller, not planned:** the ratchet cannot see the 11 header elements. Making the fixtures serve them would put the caps at 117/136 after this section, which contradicts "caps stay 109/128".
- **Order matters:** B7b alone on the real page with a number would read 124/143.
- **Today (0 touches):** `today-density.test.jsx` stays 31 / 112 / 1,662 (fixture phones are null). Measured in a scratch copy with a served number on every row: per row 32, page 1,712. That is the quiet `tel:` link `ContactActions` already draws for any served `phone_e164`, and it is P1/B4's number to know.
- **The dialog (no census, counted by hand):** the `.cd-head` subtree is 19 elements with no number and 20 with a served phone at HEAD. After B7b it is 20 and 23.

## Pins — measured

| Pin | File:line | What would move it | Price |
|---|---|---|---|
| OD-02 short line inside `.cs-head__money` | `CustomerCase.test.jsx:840` | B5 keeps `arrears-hold` in the header | 0 |
| `case-ladder-line`, `arrears-hold` outside every `<details>` | `CustomerCase.test.jsx:903-910` | B5 keeps both on the face | 0 |
| `money-position` carries the ask and the CF1 fee line | `CustomerCase.test.jsx:517-526` | B5 `slot="face"` keeps both; the fold part has a different test id | 0 |
| `#mp-note-toggle` reachable, fail-safe rules | `MoneyPosition.test.jsx:66,94,101,113,114,123` (12 tests) | `slot` undefined renders exactly as before | 0 |
| `mp-note-toggle` / `arrears-hold-toggle` in the case tests | `CustomerCase.test.jsx` | **measured 0 occurrences**; ids are kept, now inside the fold | 0 |
| case-page caps 109 / 128 | `density.test.jsx:370,393,480,505` | measured unchanged | 0 |
| `"x" in phone_masked`; SHEET rows `phone_e164 is None` | `test_journey_rebuild.py:63` and `:65` | `phone_masked` never touched; the store resets per test (conftest) | 0 |
| `Customer.phone_e164 is None` on the fixture objects | `test_fixture_honesty.py:134,139` | serve-time overlay; the fixture object is never mutated | 0 |
| `phone_on_file` false on the placeholder, true on a mask | `test_round5_data_flow.py:544-550` | no override in that test; `phone_on_file` = import answer when no override | 0 |
| seven top-level keys differ on a CLOSED row | `test_round4.py:775` | the new keys are nested in `customer`, on both rows | 0 |
| every router module's act lands in the log | `test_audit_coverage.py` | the new route is on an already-covered router | 0 |
| hero draws no call button; the no-phone sentence | `Today.test.jsx:218-226` | Today.jsx untouched; only the case page passes `why` | 0 |
| a row with a served phone dials | `Today.test.jsx:238-243` | unchanged | 0 |
| ContactActions standalone says why | `CaseContactDrawer.test.jsx:209` | unchanged | 0 |
| Today caps 31 / 112 / 1,662 | `today-density.test.jsx:139-140,152` | fixture phones null; measured unchanged | 0 |

Measured in scratch copies with B5 + B7a + B7b applied:
- **Frontend:** all 726 existing tests green, plus 35 added.
- **Backend:** B6 applied with no database, 959 passed, 103 skipped (DB tests skip without `pg_local` in scratch), 0 failed. The DB-backed B6 test passed against local Postgres.

---

### Task B5: The case header keeps figures; the explanations fold into "รายละเอียดการคำนวณ"

**Files:**
- Modify: `frontend/src/components/MoneyPosition.jsx` (whole file, 139 lines: `slot` prop, exported `noteDisclosure`)
- Modify: `frontend/src/screens/CustomerCase.jsx`:
  - line 2 (`Link`) and line 15 (`noteDisclosure`)
  - after 472 (`calcHas`)
  - 609–631 (hold toggle out, `slot="face"`)
  - 675–692 (ladder toggle out)
  - after 1481 (the fold section)
- Modify: `frontend/src/i18n-today.js` (7 keys, end of `TODAY_EN` before line 610 and end of `TODAY_TH` before line 1146)
- Modify: `frontend/src/today.css` (one rule after line 532)
- Test: `frontend/src/screens/CustomerCase.header.test.jsx` (create), `frontend/src/components/MoneyPosition.slot.test.jsx` (create)

**Interfaces:**
- Consumes: the served `work_item.money_position` (`note_th`, `penalty_formula_th`, `penalty_invoicing_enabled`, `penalty_rule_owner`, `penalty_accrued_unbilled`, `amount_to_ask`, `sheet_late_fees`), `work_item.ladder`, and `allocation_note_th` / `allocation_note_standing_th`. All are served at HEAD.
- Produces:
  - `export function noteDisclosure(mp, { compact, uniformHeld, discloseNote, foldDecided }) -> { held, accrued, shortClause, noteBehind, noteOnFace }`
  - `<MoneyPosition … slot={undefined | 'face' | 'fold'} />`. Undefined behaves as before. `'face'` draws the ask and the refusals only. `'fold'` draws only the disclosure, wrapped in `data-testid="money-position-fold"`.
  - Case page:
    - `section[aria-label="รายละเอียดการคำนวณ"]` holds `details[data-testid="calc-fold"]` (closed), mounted only when `calcHas`.
    - Inside it: `money-position-fold`, `#arrears-hold-toggle` / `arrears-hold-detail-field`, `#ladder-toggle` / `#ladder-detail`.
    - Owner only: `data-testid="calc-settings"` holding `calc-settings-late_payment_daily_rate` → `/settings?field=late_payment_daily_rate` and `calc-settings-late_payment_grace_days` → `/settings?field=late_payment_grace_days`.
  - i18n keys, EN / TH:
    - `case.calc.title` "How these figures are worked out" / "รายละเอียดการคำนวณ"
    - `case.calc.holdWhy` "Why the arrears have not moved" / "ทำไมยอดค้างยังไม่เปลี่ยน"
    - `case.calc.ladderWhy` "Why this ladder rung" / "ทำไมบันไดขั้นนี้"
    - `case.calc.settingsLead` "These come from Settings:" / "ค่านี้มาจากที่ตั้งค่า:"
    - `case.calc.settingsLink` "Edit in Settings — {field}" / "แก้ไขที่ตั้งค่า — {field}"
    - `case.calc.field.late_payment_daily_rate` "penalty rate" / "อัตราค่าปรับ"
    - `case.calc.field.late_payment_grace_days` "grace days" / "ระยะผ่อนผัน"

**Pins:** 0.
- `CustomerCase.test.jsx:840`, `:903-910` and `:517-526` stay green without an edit.
- `MoneyPosition.test.jsx` (12 tests) stays green without an edit.
- Density before 109 / 128, after 109 / 128 (fixture). Real served header 120 / 139 → 117 / 136 (scratch).

- [ ] **Step 1: Confirm the base and the key names are free**

Run: `git log --oneline -8 && grep -n "'case\.calc" frontend/src/i18n-*.js`
Expected: HEAD is `91b8519` or a descendant (read any newer commit that touches `CustomerCase.jsx`, `MoneyPosition.jsx` or `i18n-today.js` before continuing); the grep prints nothing.

- [ ] **Step 2: Write the failing tests**

```jsx
// frontend/src/components/MoneyPosition.slot.test.jsx
// Feedback Round 1 / WP8: MoneyPosition's `slot` splits the block between the case
// header ('face') and the calculation fold ('fold'). ADDED tests; MoneyPosition.test.jsx
// (the fail-safe rules, no slot) is untouched and must stay green as it is.
import { describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'
import { MoneyPosition, noteDisclosure } from './MoneyPosition.jsx'

const DECIDED = {
  amount_to_ask: '2999.00', penalty_invoicing_enabled: true, penalty_rule_owner: 'CF1 / OD-31',
  penalty_accrued_unbilled: '74.98', penalty_formula_th: 'ยอดค้าง × 0.03%/วัน × (จำนวนวันค้าง − 0)',
  note_th: 'ยอดที่ขอให้ลูกค้าชำระคือค่างวดค้าง',
}
const HELD = { ...DECIDED, penalty_invoicing_enabled: false, penalty_rule_owner: 'Legal', penalty_accrued_unbilled: '0' }
const CASE_PAGE = { discloseNote: true, foldDecided: true }

describe('MoneyPosition slot', () => {
  it('face draws the figures and refusals and never the disclosure', () => {
    const { container } = renderIn('th', <MoneyPosition mp={{ ...HELD, sheet_late_fees: '430.00' }} arrears="2999.00" {...CASE_PAGE} slot="face" />)
    expect(screen.getByTestId('penalty-held')).toHaveTextContent('Legal')
    expect(screen.getByText(/ชีต: ค่าปรับ/)).toHaveTextContent('430.00')
    expect(container.querySelector('#mp-note-toggle')).toBeNull()
  })

  it('face renders nothing when the only thing to draw was the disclosure', () => {
    const { container } = renderIn('th', <MoneyPosition mp={DECIDED} arrears="2999.00" {...CASE_PAGE} slot="face" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('fold draws only the disclosure, and it still opens', () => {
    const { container } = renderIn('th', <MoneyPosition mp={DECIDED} arrears="2999.00" {...CASE_PAGE} slot="fold" />)
    expect(screen.queryByTestId('money-position')).toBeNull()
    expect(screen.getByTestId('money-position-fold')).toBeInTheDocument()
    fireEvent.click(container.querySelector('#mp-note-toggle'))
    expect(screen.getByTestId('mp-formula-detail-field')).toHaveTextContent('0.03%/วัน')
  })

  it('fold renders nothing when the note is on the face instead (the fail-safe direction)', () => {
    const { container } = renderIn('th', <MoneyPosition mp={DECIDED} arrears="2999.00" slot="fold" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('noteDisclosure answers exactly what the component draws', () => {
    expect(noteDisclosure(DECIDED, CASE_PAGE).noteBehind).toBe(true)
    expect(noteDisclosure(DECIDED, {}).noteBehind).toBe(false)
    expect(noteDisclosure(HELD, CASE_PAGE)).toMatchObject({ shortClause: true, noteBehind: true, noteOnFace: false })
    expect(noteDisclosure(null, CASE_PAGE).noteBehind).toBe(false)
  })
})
```

```jsx
// frontend/src/screens/CustomerCase.header.test.jsx
// Feedback Round 1 / WP8 (design F12 (a), approved 2026-09-15): "the case header has
// too much detail — put it elsewhere". The header keeps figures; everything that
// explains a figure folds into ONE closed "รายละเอียดการคำนวณ" section beside the
// history fold. The refusals (OD-02's short line, OD-04's badge, CF1's clauses) stay
// on the face — contract §3. ADDED tests; no pinned test is edited.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import CustomerCase from './CustomerCase.jsx'

vi.mock('../api.js', () => ({
  api: {
    caseDetail: vi.fn(), recordLinkSent: vi.fn(), dictionary: vi.fn(), setNextAction: vi.fn(),
    setDcStatus: vi.fn(), setPaymentStatus: vi.fn(), setNplType: vi.fn(), logContact: vi.fn(),
    logCaseContact: vi.fn(), retractContact: vi.fn(), closeCasePtp: vi.fn(), renegotiatePtp: vi.fn(),
    requestReview: vi.fn(), closeCaseIssue: vi.fn(), requestPower: vi.fn(), powerAct: vi.fn(),
    confirmSlip: vi.fn(), setCustomerPhone: vi.fn(),
  },
}))

const Page = () => (
  <MemoryRouter initialEntries={['/customers/cu-1']}>
    <Routes>
      <Route path="/customers/:customerUid" element={<CustomerCase />} />
      <Route path="/settings" element={<p data-testid="settings-page">settings</p>} />
    </Routes>
  </MemoryRouter>
)

// The three blocks routers/journey.py and routers/today.py serve on 212 of 212 cases
// (measured 2026-09-15 on the seeded book): a decided penalty's note and formula, the
// ladder, and the standing OD-02 note.
const MONEY_POSITION = {
  amount_to_ask: '2999.00', instalments_overdue: '2999.00', penalty_accrued_unbilled: '74.98',
  per_contract: [{ uid: 'K-1-L', product: 'LEASE', instalments_overdue: '2999.00', penalty: '74.98', oldest_dpd: 13, pmt: '2999.00', fee_state: null }],
  contract_count: 1, summed_across_contracts: false, penalty_invoicing_enabled: true,
  penalty_rate_pct_per_day: '0.03', penalty_rule_owner: 'CF1 / OD-31', penalty_grace_days: 0,
  penalty_formula_th: 'ยอดค้าง × 0.03%/วัน × (จำนวนวันค้าง − 0)', sheet_late_fees: null, sheet_days_late: null,
  note_th: 'ยอดที่ขอให้ลูกค้าชำระคือค่างวดค้าง 2999.00 บาท (ยอดค้างบนหน้าจอ); แอปคำนวณค่าปรับไว้ต่างหากอีก 74.98 บาท',
}
const LADDER = {
  kind: 'LEASE', stage: 'NORMAL', indicative: 'NOTICE_30', mode: 'ASSISTED', pending_decision: 'OD-04',
  source: 'ladder.py', note: 'Stages move only by human action.',
  steps: [{ stage: 'NOTICE_30', day: 30, act_th: 'แจ้งเตือนและให้เวลาชำระ' },
          { stage: 'NPL_DECLARED_90', day: 90, act_th: 'ประกาศ NPL' }],
}
const STANDING = 'การจัดสรรเข้างวดรอคำตัดสิน OD-02 (ลำดับการจัดสรร) ยอดค้างจึงยังไม่เปลี่ยนจนกว่าบัญชีจะตัดสิน'

const CUSTOMER = { uid: 'cu-1', customer_no: '99999000112', display_name: 'ลูกค้าทดสอบ 0187',
                   phone_masked: '08x-xxx-8720', phone_e164: null, line_id: null, contract_count: 1, officer: 'nantapol' }

const detail = (over = {}) => ({
  case: {
    uid: 'case-1', customer_uid: 'cu-1', customer_no: '99999000112', volt_id: '99999000112_VOLT', product: 'LEASE',
    officer_uid: 'nantapol', payment_status: 'LATE', payment_status_system: 'LATE', dc_status: 'CONTACT_BACK',
    npl_type: null, next_action: 'CALL', next_action_on: '2026-10-29', last_contact_at: null, last_contact_by: null,
    last_result: null, open_ptp_uid: null, broken_ptp_count: 0, kept_ptp_count: 0, renegotiation_count: 0,
    open_issue_uid: null, power_state: 'ON', power_uid: null, review_uid: null, sheet: {},
  },
  work_item: {
    customer: CUSTOMER, entity: 'SPV', company_id: 'CO-SPV', aggregate_overdue: '2999.00',
    aggregate_outstanding: '212928.99', oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL',
    open_ptp: null, contact_lock: { state: 'OPEN' }, money_position: MONEY_POSITION, ladder: LADDER,
  },
  customer: { ...CUSTOMER, volt_id: '99999000112_VOLT' },
  contracts: [{ uid: 'K-1-L', product: 'LEASE', entity: 'SPV', status: 'PAST_DUE', principal: '176411.76',
                term_months: 96, first_due: '2024-09-10', paid_through: 25, derivation: {}, fee_state: null }],
  month_grid: [], contact_log: [], ptps: [], issues: [], reviews: [], power: [], sheet_row: {},
  invoices: [], receipts: [], events: [], allocation_note_standing_th: STANDING,
  ...over,
})

async function open(data = detail()) {
  api.caseDetail.mockResolvedValue(data)
  const view = renderIn('th', <Page />)
  await screen.findByRole('heading', { level: 1, name: 'ลูกค้าทดสอบ 0187' })
  return view
}

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER')
  setOfficer('nantapol')
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
})

describe('WP8 — the case header keeps figures only', () => {
  it('draws no explanation toggle in the header', async () => {
    const { container } = await open()
    const header = container.querySelector('header.cs-head')
    expect(header.querySelectorAll('.row-expand__toggle')).toHaveLength(0)
    expect(within(header).queryByText('ยอดนี้คิดอย่างไร')).toBeNull()
  })

  it('keeps the refusals on the face: OD-02 beside the money, OD-04 on the ladder line', async () => {
    const { container } = await open()
    const money = container.querySelector('.cs-head__money')
    expect(within(money).getByTestId('arrears-hold')).toHaveTextContent('รอจัดสรร OD-02')
    expect(screen.getByTestId('case-ladder-line')).toHaveTextContent('OD-04')
    for (const id of ['arrears-hold', 'case-ladder-line']) {
      expect(screen.getByTestId(id).closest('details')).toBeNull()
    }
  })

  it('puts every explanation in one closed fold, placed right after the history fold', async () => {
    const { container } = await open()
    const fold = screen.getByTestId('calc-fold')
    expect(fold.tagName).toBe('DETAILS')
    expect(fold).not.toHaveAttribute('open')
    expect(within(fold).getByRole('heading', { level: 2 })).toHaveTextContent('รายละเอียดการคำนวณ')
    for (const id of ['mp-note-toggle', 'arrears-hold-toggle', 'ladder-toggle']) {
      expect(container.querySelector(`#${id}`).closest('details')).toBe(fold)
    }
    const history = screen.getByTestId('history-fold').closest('section')
    expect(history.nextElementSibling).toBe(fold.closest('section'))
  })

  it('still opens each explanation in place: the note and formula, the OD-02 sentence, the ladder', async () => {
    const { container } = await open()
    fireEvent.click(container.querySelector('#mp-note-toggle'))
    expect(screen.getByTestId('mp-note-detail-field')).toHaveTextContent('ยอดที่ขอให้ลูกค้าชำระคือค่างวดค้าง')
    expect(screen.getByTestId('mp-formula-detail-field')).toHaveTextContent('0.03%/วัน')
    fireEvent.click(container.querySelector('#arrears-hold-toggle'))
    expect(screen.getByTestId('arrears-hold-detail-field')).toHaveTextContent(STANDING)
    fireEvent.click(container.querySelector('#ladder-toggle'))
    expect(container.querySelector('#ladder-detail')).toBeInTheDocument()
  })

  it('names what each toggle in the fold opens, never a bare "รายละเอียด" or "ทำไม"', async () => {
    const { container } = await open()
    expect(container.querySelector('#mp-note-toggle')).toHaveTextContent('ยอดนี้คิดอย่างไร')
    expect(container.querySelector('#arrears-hold-toggle')).toHaveTextContent('ทำไมยอดค้างยังไม่เปลี่ยน')
    expect(container.querySelector('#ladder-toggle')).toHaveTextContent('ทำไมบันไดขั้นนี้')
  })

  it('mounts no fold when nothing on the case needs explaining', async () => {
    await open(detail({ allocation_note_standing_th: null,
                        work_item: { ...detail().work_item, money_position: null, ladder: null } }))
    expect(screen.queryByTestId('calc-fold')).toBeNull()
  })

  it('keeps a held penalty\'s short clause on the face and only its long note in the fold', async () => {
    const held = { ...MONEY_POSITION, penalty_invoicing_enabled: false, penalty_rule_owner: 'Legal' }
    const { container } = await open(detail({ work_item: { ...detail().work_item, money_position: held } }))
    const money = container.querySelector('.cs-head__money')
    expect(within(money).getByTestId('penalty-held')).toHaveTextContent('Legal')
    expect(container.querySelector('#mp-note-toggle').closest('details')).toBe(screen.getByTestId('calc-fold'))
  })
})

describe('WP8 — "editable": the settings the figures come from', () => {
  it('offers the Owner a link to each setting, opening Settings at that field', async () => {
    setRole('OWNER')
    await open()
    const links = within(screen.getByTestId('calc-settings'))
    expect(links.getByTestId('calc-settings-late_payment_daily_rate'))
      .toHaveAttribute('href', '/settings?field=late_payment_daily_rate')
    expect(links.getByTestId('calc-settings-late_payment_grace_days'))
      .toHaveAttribute('href', '/settings?field=late_payment_grace_days')
    expect(links.getByTestId('calc-settings-late_payment_daily_rate')).toHaveTextContent('แก้ไขที่ตั้งค่า — อัตราค่าปรับ')
    fireEvent.click(links.getByTestId('calc-settings-late_payment_grace_days'))
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument()
  })

  it('shows no settings link to anyone else', async () => {
    for (const role of ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OPS']) {
      setRole(role)
      const { unmount } = await open()
      expect(screen.queryByTestId('calc-settings')).toBeNull()
      unmount()
    }
  })
})
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/MoneyPosition.slot.test.jsx src/screens/CustomerCase.header.test.jsx`
Expected: FAIL. The slot file fails at import (`noteDisclosure` is not exported). The header file fails: the header holds 3 `.row-expand__toggle`, `calc-fold` is not found, and the toggle labels read "รายละเอียด" and "ทำไม".

- [ ] **Step 4: Measure BEFORE (the scratch copy that serves the header blocks)**

The fixtures do not carry `money_position`, `ladder` or `allocation_note_standing_th`, so B5's give-back is invisible to them. Measure in a scratch copy under your own scratchpad (`$SCRATCH`):

```bash
mkdir -p "$SCRATCH/fe" && cp -R frontend/src frontend/package.json frontend/vite.config.js frontend/index.html "$SCRATCH/fe/"
ln -s /Users/parattakorn/volt-debt-prototype/frontend/node_modules "$SCRATCH/fe/node_modules"
cp frontend/src/density.test.jsx "$SCRATCH/fe/src/measure.test.jsx"
```

Append this block to `$SCRATCH/fe/src/measure.test.jsx`. The file's own `PRE_CONTACT`, `WORKED`, `PAYMENT_SUMMARY`, `PAYMENT_POSITION`, `census` and `mount` are in scope.

```jsx
// ---- scratch measure: the header blocks the real book serves on 212/212, and a phone override
const MP_SERVED = {
  amount_to_ask: '2999.00', instalments_overdue: '2999.00', penalty_accrued_unbilled: '74.98',
  per_contract: [{ uid: 'K-1-L', product: 'LEASE', instalments_overdue: '2999.00', penalty: '74.98', oldest_dpd: 13, pmt: '2999.00', fee_state: null }],
  contract_count: 1, summed_across_contracts: false, penalty_invoicing_enabled: true,
  penalty_rate_pct_per_day: '0.03', penalty_rule_owner: 'CF1 / OD-31', penalty_grace_days: 0,
  penalty_formula_th: 'ยอดค้าง × 0.03%/วัน × (จำนวนวันค้าง − 0)', sheet_late_fees: null, sheet_days_late: null,
  note_th: 'ยอดที่ขอให้ลูกค้าชำระคือค่างวดค้าง 2999.00 บาท',
}
const LADDER_SERVED = {
  kind: 'LEASE', stage: 'NORMAL', indicative: 'NOTICE_30', mode: 'ASSISTED', pending_decision: 'OD-04', markers: {},
  steps: [{ stage: 'NOTICE_30', day: 30, act_th: 'แจ้งเตือนและให้เวลาชำระ' }, { stage: 'NPL_DECLARED_90', day: 90, act_th: 'ประกาศ NPL' }],
}
const OVERRIDE = { phone_e164: '+66812345678', display: '081-234-5678', kind: 'MOBILE', set_by: 'thip',
                   set_at: '2026-10-23T09:15:00+07:00', reason: 'x', durable: true }
const PHONES = { asFixture: {}, override: { phone_e164: OVERRIDE.phone_e164, phone_on_file: true, phone_on_sheet: true, phone_override: OVERRIDE } }
function served(base, header, phone) {
  return {
    ...base, payment_summary: PAYMENT_SUMMARY, customer: { ...base.customer, ...PHONES[phone] },
    ...(header ? { allocation_note_standing_th: 'การจัดสรรเข้างวดรอคำตัดสิน OD-02' } : {}),
    work_item: { ...base.work_item, customer: { ...base.work_item.customer, ...PHONES[phone] }, payment_position: PAYMENT_POSITION,
                 ...(header ? { money_position: MP_SERVED, ladder: LADDER_SERVED } : {}) },
  }
}
describe('scratch measure', () => {
  beforeEach(() => Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true }))
  for (const [name, base] of [['PRE', PRE_CONTACT], ['WORKED', WORKED]]) {
    for (const header of [false, true]) {
      for (const phone of ['asFixture', 'override']) {
        it(`${name} header=${header} phone=${phone}`, async () => {
          const { container } = await mount(served(base, header, phone))
          // eslint-disable-next-line no-console
          console.log(`MEASURE ${name} header=${header} phone=${phone} visible=${census(container).visible}`)
        })
      }
    }
  }
})
```

Run: `cd "$SCRATCH/fe" && npx vitest run src/measure.test.jsx 2>&1 | grep -E "^MEASURE|^PRE-CONTACT|^WORKED"`
Expected at HEAD: `PRE header=false phone=asFixture visible=109`, `WORKED … =128`, `PRE header=true phone=asFixture visible=120`, `WORKED header=true phone=asFixture visible=139`, `PRE header=false phone=override visible=110`, `PRE header=true phone=override visible=121`, `WORKED header=true phone=override visible=140`. **Paste the lines.**

- [ ] **Step 5: Implement `MoneyPosition.jsx` — replace the whole file with**

```jsx
import { useState } from 'react'
import { useT } from '../prefs.jsx'
import { format } from './Money.jsx'
import { RowExpandToggle, RowExpandField } from './RowPattern.jsx'
import { PendingBadge } from './Notice.jsx'

// UAT round-2 (J-07 / J-31): beside ยอดค้าง the officer needs the figure to ASK
// for, and the sheet's late-fee line the app does not yet charge (CF1). Both come
// from work_item.money_position as the API serves it; nothing is added up here.
// Renders nothing when the API does not carry the block (older backend).

// Round-3, R2-D02/R3-D01 (ledger, this round): the row and the header must never
// disagree about what "held" means. Exported so `Today.jsx` and `WorkBook.jsx` share
// this one definition instead of each computing their own copy.
export function penaltyHeld(mp) {
  const owner = typeof mp?.penalty_rule_owner === 'string' ? mp.penalty_rule_owner.trim() : ''
  return mp?.penalty_invoicing_enabled === false && owner !== ''
}

// Feedback Round 1 / WP8 (design F12 (a), approved 2026-09-15): the disclosure rules,
// exported, so CustomerCase can ask "will this block put anything in the calculation
// fold?" and get the SAME answer the component gives itself — never a second copy.
export function noteDisclosure(mp, { compact = false, uniformHeld = false, discloseNote = false, foldDecided = false } = {}) {
  if (!mp || typeof mp !== 'object') return { held: false, accrued: 0, shortClause: false, noteBehind: false, noteOnFace: false }
  // R1-C02. The CF1 refusal's carrier on a queue row is NOT sheet_late_fees — the
  // sheet's fee cell is filled on 1 row in 63, while note_th names CF1 and OD-31 on
  // 63 of 63. Moving note_th into the expand therefore took the refusal off the
  // default view on 62 rows. The API isolates the refusal itself as two fields
  // (routers/journey.py:166,168): penalty_invoicing_enabled = false, with
  // penalty_rule_owner naming who has not decided. That clause is one short line, so
  // the row can carry the refusal without carrying the 200-character sentence.
  const held = penaltyHeld(mp)
  const accrued = Number(mp.penalty_accrued_unbilled ?? 0) || 0
  // Round-3 (ruling 1's proviso, R2-D02): while CF1 is uniform across the row's own
  // table/tier-group, the band + column mark carry the refusal and this row-level
  // sentence is silent — it never disappears by omission, because `uniformHeld`
  // defaults to false, so a caller that forgets the prop keeps today's behaviour (the
  // sentence renders on every held row). The moment a group stops being uniformly
  // held, the rows that lose the header mark get this sentence back automatically.
  //
  // Round 4, ruling 54: `discloseNote` widens this SAME short clause to the
  // non-compact case (CustomerCase, this round only). It is the refusal line ruling
  // 54 keeps on the face while the long note_th — today the only place naming
  // CF1/OD-31 on this page — moves behind a toggle.
  const shortClause = (compact || discloseNote) && held && (accrued > 0 || !uniformHeld)
  // The long sentence stays on the face UNLESS something shorter naming the same two
  // decision ids is ALREADY standing in its place — never "discloseNote hides it"
  // alone. A case that stops qualifying for the short clause (held flips false, or a
  // caller forgets discloseNote) gets the full refusal back on the face
  // automatically — the same fail-safe direction this file's other default (line 1)
  // already uses, applied to this switch too.
  //
  // Arina, 2026-09-14 ("overview first", the slimmer case header): once ruling 87
  // decided the rate, penalty_invoicing_enabled is true and the long sentence carries
  // no refusal at all — it explains a figure. With nothing held there is nothing for
  // the face to protect, so `foldDecided` (the case page only; Today's hero still
  // prints it) folds it too. The fail-safe is untouched: a HELD penalty still folds
  // only while the short clause stands in for it.
  const noteBehind = !compact && Boolean(mp.note_th) && discloseNote && (shortClause || (foldDecided && !held))
  const noteOnFace = !compact && Boolean(mp.note_th) && !noteBehind
  return { held, accrued, shortClause, noteBehind, noteOnFace }
}

// Feedback Round 1 / WP8: `slot` splits this block across the case page. 'face' draws
// what sits beside the figure (the ask and the CF1 refusals); 'fold' draws only the
// disclosure, for the page's "รายละเอียดการคำนวณ" fold. Undefined — every other
// caller and every MoneyPosition.test.jsx case — draws both in place, as before.
export function MoneyPosition({ mp, compact = false, arrears, uniformHeld = false, discloseNote = false, foldDecided = false, slot }) {
  const t = useT()
  // Round 4, ruling 54 (shell-disclosure §6.1): the one new toggle this component
  // grows. Internal state, not a prop — each mounted MoneyPosition owns its own
  // open flag, the way a queue row's own RowExpandRow does. Only CustomerCase
  // passes discloseNote this round (E7: no board card may, until that shape is
  // costed), so today only one instance of this toggle ever exists at a time —
  // see the fixed `mp-note-toggle` id below. (WP8: the case page mounts two
  // instances, 'face' and 'fold'; only the 'fold' one ever draws the toggle.)
  const [noteOpen, setNoteOpen] = useState(false)
  if (!mp || typeof mp !== 'object') return null
  const hasAsk = mp.amount_to_ask !== undefined && mp.amount_to_ask !== null
  const hasFees = mp.sheet_late_fees !== undefined && mp.sheet_late_fees !== null && mp.sheet_late_fees !== ''
  const owner = typeof mp.penalty_rule_owner === 'string' ? mp.penalty_rule_owner.trim() : ''
  const { held, accrued, shortClause, noteBehind, noteOnFace } = noteDisclosure(mp, { compact, uniformHeld, discloseNote, foldDecided })
  const rendersAsk = hasAsk && format(mp.amount_to_ask) !== format(arrears)
  // Ruling 54's disclosure (shell-disclosure §6.1/§5.3). Gated on noteBehind — a
  // boolean already computed from the DATA above — never on RowExpandField's own
  // empty-children guard, so the control never promises a derivation it cannot
  // deliver (the WorkBook.jsx:296-297 R3-D12 law, generalised here).
  const disclosure = noteBehind ? (
    <>
      {/* On the case page this sits under the arrears-hold toggle, and two buttons
          both reading "รายละเอียด" name nothing; a folded decided note says what
          it opens. The held path keeps the label it always had. */}
      <RowExpandToggle id="mp-note-toggle" controls="mp-note-detail" panelMounted={noteOpen}
                        label={foldDecided && !held ? t('mp.noteToggle') : undefined}
                        open={noteOpen} onToggle={() => setNoteOpen((v) => !v)} />
      {noteOpen && (
        <div id="mp-note-detail" className="row-expand__body" role="group" aria-labelledby="mp-note-toggle">
          <RowExpandField label={t('case.derivationOpen')} testId="mp-note-detail-field">
            {mp.note_th}
          </RowExpandField>
          {/* penalty_rate_pct_per_day / penalty_grace_days are CUT (shell-disclosure
              §2.1/§7.3): routers/journey.py:177 interpolates both into
              penalty_formula_th verbatim, so a served rule string carries them —
              printing a served formula is not the client arithmetic api.js:1-4
              forbids. Badged as indicative (L4) at the moment it becomes visible,
              using the register's own owner for CF1/OD-31 — both "open". */}
          {Boolean(mp.penalty_formula_th) && (
            <RowExpandField label={t('mp.formula')} testId="mp-formula-detail-field">
              {mp.penalty_formula_th}{' '}<PendingBadge decision={mp.penalty_rule_owner} owner="open" />
            </RowExpandField>
          )}
        </div>
      )}
    </>
  ) : null
  if (slot === 'fold') return disclosure ? <div className="mp" data-testid="money-position-fold">{disclosure}</div> : null
  const face = rendersAsk || noteOnFace || hasFees || shortClause
  if (!face && (slot === 'face' || !noteBehind)) return null
  return (
    <div className={`mp${compact ? ' mp--compact' : ''}`} data-testid="money-position">
      {rendersAsk && (
        <p className="mp__ask">
          {t('mp.amountToAsk', { amount: format(mp.amount_to_ask) })}
        </p>
      )}
      {/* UX round 1, measured on the running desk: note_th is the API's ~200-character
          sentence about the temporary penalty rate, OD-31 and CF1. In a queue cell it
          ran to eight lines on EVERY row and made the money column the loudest thing
          on the page by area. In the compact (row) variant the sentence is not
          clamped — a clamp ends mid-sentence and reads as complete — it moves whole
          into the row expand, one click from the figure it explains. The hero, the
          drawer and (unless discloseNote's short clause is standing in for it) the
          case page still print it in full. */}
      {noteOnFace && <p className="mp__note">{mp.note_th}</p>}
      {/* CF1, on the row or the case page (R1-C02, widened by ruling 54). The full
          sentence above says this among five other things; here it is said alone, in
          one line, so the refusal never depends on the officer opening anything.
          noteOnFace and this line are never both true at once while note_th exists —
          exactly one of them (or neither, on a case with no penalty story at all)
          names CF1/OD-31 on the face. Round 3: silent while the group is uniformly
          held (the band + mark carry it instead); returns the moment it is not. */}
      {shortClause && (
        <p className="mp__note mp__note--refusal" data-testid="penalty-held">
          {accrued > 0
            ? t('mp.penaltyHeldAmount', { amount: format(mp.penalty_accrued_unbilled), owner })
            : t('mp.penaltyHeld', { owner })}
        </p>
      )}
      {/* CF1 — a deliberate refusal: the sheet charges a late fee, the app does not,
          and nobody has decided. It is never clamped and never demoted (design
          contract §3, "the deliberate refusals stay refused"). */}
      {hasFees && <p className="mp__note mp__note--refusal">{t('mp.sheetLateFees', { fees: format(mp.sheet_late_fees) })}</p>}
      {slot !== 'face' && disclosure}
    </div>
  )
}
```

- [ ] **Step 6: Implement `CustomerCase.jsx`**

(a) Line 2: `import { Link, useParams, useSearchParams } from 'react-router-dom'`. Line 15: `import { MoneyPosition, noteDisclosure } from '../components/MoneyPosition.jsx'`.

(b) Directly after lines 470–472 (`const indicativeStep = …`), add:

```jsx
  // Feedback Round 1 / WP8 (design F12 (a)): the header keeps figures; this says
  // whether anything on THIS case explains a figure, so the calculation fold mounts
  // only when it has something in it (R3-D12's rule). The Owner also gets it for the
  // settings links whenever a money position is served.
  const calcHas = noteDisclosure(item?.money_position, { discloseNote: true, foldDecided: true }).noteBehind
    || Boolean(arrearsHold && allocationNote) || ladderSteps.length > 0
    || (role === 'OWNER' && Boolean(item?.money_position))
```

(c) Lines 610–631: delete the two `{arrearsHold && allocationNote && …}` blocks (the `RowExpandToggle id="arrears-hold-toggle"` and its `arrears-hold-detail` panel). Keep line 609 (`<p className="cs-hold" data-testid="arrears-hold">`) and the two comment blocks above `MoneyPosition`. Replace line 631 with:

```jsx
          {/* WP8: slot="face" — the ask and the CF1 refusals stay beside the figure;
              the "how this figure is worked out" toggle draws in the calculation fold. */}
          <MoneyPosition mp={item?.money_position} arrears={item?.aggregate_overdue} discloseNote foldDecided slot="face" />
```

(d) Lines 684–690: delete the `RowExpandToggle id="ladder-toggle"` and the `{ladderOpen && (…LadderStep detail…)}` block. Keep the ladder label, the `case-ladder-line` paragraph and its `PendingBadge`.

(e) After line 1481 (the `</section>` that closes the history section, before the `{/* --- invoices and money in` comment), insert:

```jsx
        {/* --- how the figures are worked out --------------------------------------- */}
        {/* Feedback Round 1 / WP8 (design F12 (a), Arina 2026-09-15): "too much detail in
            the header — put it elsewhere". Every toggle that explained a header figure
            lives here now, beside the history fold and closed by default. The refusals
            they explain (OD-02's short line, OD-04's badge, CF1's clauses) stay on the
            face (contract §3; CustomerCase.test.jsx:903-910). "Editable" (F12 (a)): the
            values that are settings get a link for the Owner. */}
        {calcHas && (
          <section className="cs-card cs-card--wide" aria-label={t('case.calc.title')}>
            <details className="cs-disclose" data-testid="calc-fold">
              <summary className="cs-disclose__summary"><h2 className="cs-card__title">{t('case.calc.title')}</h2></summary>
              <MoneyPosition mp={item?.money_position} arrears={item?.aggregate_overdue} discloseNote foldDecided slot="fold" />
              {role === 'OWNER' && item?.money_position && (
                <p className="cs-row" data-testid="calc-settings">
                  <span className="td-quiet">{t('case.calc.settingsLead')}</span>
                  {['late_payment_daily_rate', 'late_payment_grace_days'].map((key) => (
                    <Link key={key} to={`/settings?field=${key}`} data-testid={`calc-settings-${key}`}>
                      {t('case.calc.settingsLink', { field: t(`case.calc.field.${key}`) })}
                    </Link>
                  ))}
                </p>
              )}
              {arrearsHold && allocationNote && (
                <div className="cs-calc__item">
                  {/* Ruling 13 (R3-E08): the OD-02 hold's full explanation, keyboard-reachable. */}
                  <RowExpandToggle id="arrears-hold-toggle" controls="arrears-hold-detail" panelMounted={holdOpen}
                                    label={t('case.calc.holdWhy')} open={holdOpen} onToggle={() => setHoldOpen((v) => !v)} />
                  {holdOpen && (
                    <div id="arrears-hold-detail" className="row-expand__body" role="group" aria-labelledby="arrears-hold-toggle">
                      <RowExpandField label={t('case.allocationPending')} testId="arrears-hold-detail-field">
                        {allocationNote}
                      </RowExpandField>
                    </div>
                  )}
                </div>
              )}
              {ladderSteps.length > 0 && (
                <div className="cs-calc__item">
                  {/* Ruling 56 path 2: LadderStep verbatim, one step from the ladder line. */}
                  <RowExpandToggle id="ladder-toggle" controls="ladder-detail" panelMounted={ladderOpen} label={t('case.calc.ladderWhy')}
                                    open={ladderOpen} onToggle={() => setLadderOpen((v) => !v)} />
                  {ladderOpen && (
                    <div id="ladder-detail" className="row-expand__body" role="group" aria-labelledby="ladder-toggle">
                      <LadderStep ladder={ladder} detail />
                    </div>
                  )}
                </div>
              )}
            </details>
          </section>
        )}
```

- [ ] **Step 7: Strings and CSS**

`frontend/src/i18n-today.js`, at the end of `TODAY_EN` (after `'board.col.col_01H90': 'Escalate',`, before `}` at line 610):

```js
  // Feedback Round 1 / WP8 (design F12 (a)): the case header keeps figures; what
  // explains them folds to one section at the bottom of the page.
  'case.calc.title': 'How these figures are worked out',
  'case.calc.holdWhy': 'Why the arrears have not moved',
  'case.calc.ladderWhy': 'Why this ladder rung',
  'case.calc.settingsLead': 'These come from Settings:',
  'case.calc.settingsLink': 'Edit in Settings — {field}',
  'case.calc.field.late_payment_daily_rate': 'penalty rate',
  'case.calc.field.late_payment_grace_days': 'grace days',
```

At the end of `TODAY_TH` (after `'board.col.col_01H90': 'ส่งต่อผู้จัดการ',`, before `}` at line 1146):

```js
  'case.calc.title': 'รายละเอียดการคำนวณ',
  'case.calc.holdWhy': 'ทำไมยอดค้างยังไม่เปลี่ยน',
  'case.calc.ladderWhy': 'ทำไมบันไดขั้นนี้',
  'case.calc.settingsLead': 'ค่านี้มาจากที่ตั้งค่า:',
  'case.calc.settingsLink': 'แก้ไขที่ตั้งค่า — {field}',
  'case.calc.field.late_payment_daily_rate': 'อัตราค่าปรับ',
  'case.calc.field.late_payment_grace_days': 'ระยะผ่อนผัน',
```

`frontend/src/today.css`, after line 532 (`.cs-slip .btn { min-height: 44px; }`):

```css
/* Feedback Round 1 / WP8: one explanation per row inside the calculation fold. */
.cs-calc__item { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
```

- [ ] **Step 8: Run the focused tests, the pins, then the suite and the build**

Run: `cd frontend && npx vitest run src/components/MoneyPosition.slot.test.jsx src/screens/CustomerCase.header.test.jsx src/components/MoneyPosition.test.jsx src/screens/CustomerCase.test.jsx src/screens/CustomerCase.paymentStatus.test.jsx src/round4.test.jsx src/i18n.test.js src/density.test.jsx`
Expected: PASS (measured in scratch: 5 + 9 new; MoneyPosition 12, CustomerCase 46, paymentStatus 8, round4 45, i18n 19, density 5 unchanged).

Run: `cd frontend && npx vitest run && npx vite build`
Expected: PASS at the Task-start baseline + 14. **Paste the count.**

- [ ] **Step 9: Measure AFTER**

Run: `cd frontend && npx vitest run src/density.test.jsx 2>&1 | grep -E "^PRE-CONTACT|^WORKED"`
Expected: `PRE-CONTACT+PAY … visible=109`, `WORKED+PAY … visible=128` (unchanged).
Re-copy `CustomerCase.jsx`, `MoneyPosition.jsx`, `i18n-today.js` and `today.css` into `$SCRATCH/fe/src/…` and re-run Step 4's command.
Expected: `PRE header=true phone=asFixture visible=117`, `WORKED header=true phone=asFixture visible=136`, `PRE header=true phone=override visible=118`, `WORKED header=true phone=override visible=137`; the header=false lines unchanged. **Paste both.** If either fixture total exceeds 109/128, STOP and report: this plan spends no edit.

- [ ] **Step 10: Commit**

```bash
cat > "$SCRATCH/b5-commit.txt" <<'MSG'
feat(case): the header keeps figures — every explanation folds into "รายละเอียดการคำนวณ", with the Owner's settings links

Design WP8 / F12 (a). MoneyPosition gains a slot ('face' | 'fold') and an exported
noteDisclosure; the arrears-hold, money-note and ladder toggles move into one closed
fold beside the history fold; OD-02, OD-04 and CF1 stay on the face. Density: fixtures
109/128 unchanged; the real served header 120/139 -> 117/136 (scratch-measured).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
MSG
git add frontend/src/components/MoneyPosition.slot.test.jsx frontend/src/screens/CustomerCase.header.test.jsx
git commit -F "$SCRATCH/b5-commit.txt" -- frontend/src/components/MoneyPosition.jsx frontend/src/components/MoneyPosition.slot.test.jsx frontend/src/screens/CustomerCase.jsx frontend/src/screens/CustomerCase.header.test.jsx frontend/src/i18n-today.js frontend/src/today.css
```

---

### Task B6: A durable, audited phone number per customer — `records.customer_contact`, `customer_contact.py`, the route, every read

**Files:**
- Create: `backend/app/customer_contact.py`, `backend/tests/test_customer_phone.py`
- Modify: `backend/app/schema.sql` (append after line 274)
- Modify: `backend/app/routers/journey.py:13` (import), `:210-217` (`_work_item` customer dict)
- Modify: `backend/app/routers/today.py:9` (import), `:91-93` (two `problem_from` rows), `:694` (pre-install customer), `:835` (case-detail customer), before `:1063` (the new route)
- Modify: `backend/tests/conftest.py` (after line 52)

**Interfaces:**
- Consumes: `db.configured()`, `db.connect()` (raises `DatabaseUnreachable`), `cases.CaseError(code, detail, message_th=…, pointer=…)`, `audit.describe`, `routers/today.who`, `_case_or_404`, `problem_from`, `journey.customer_by_uid`, `migrate.apply` (tests).
- Produces:
  - Table `records.customer_contact(uid bigserial, customer_uid, phone_e164, kind, set_by, set_at, reason, active)`, with one active row per customer (`customer_contact_active_idx`).
  - `customer_contact.normalise(raw) -> (e164, kind)`. Raises `CaseError("phone_invalid", pointer="/phone")`. Mobile is `^0[689]\d{8}$`, landline `^0[2-57]\d{7}$`, with `+66` / `66` accepted.
  - `customer_contact.display(e164, kind) -> "081-234-5678" | "02-123-4567" | "053-123-456"`.
  - `customer_contact.active_for(customer_uid) -> {phone_e164, display, kind, set_by, set_at, reason, durable[, note_th]} | None`. The table is read once per request.
  - `customer_contact.phone_fields(customer_uid, customer=None) -> {phone_masked, phone_on_sheet, phone_on_file, phone_e164, phone_override}`.
  - `customer_contact.set_phone(customer_uid, raw, by, reason) -> override | None`. A None or blank `raw` clears the number. It raises `reason_required` (`/reason`), `phone_invalid`, or `phone_unchanged` (`/phone`). Audit `PHONE_SET` is written before the write. `reset()` exists for tests.
  - `POST /v1/cases/by-customer/{customer_uid}/phone`, body `{"phone": str|null, "reason": str, "by"?}` → 200 `{"customer": {"uid", ...phone_fields}}`. It returns 404 for an unknown customer, 422 `reason_required` (DEBT-COL-0447) or `phone_invalid` (DEBT-COL-0463), and 409 `phone_unchanged` (DEBT-COL-0464).
  - Every served customer object (`/v1/today`, `/v1/workbook`, `/v1/working-list`, `/v1/cases/by-customer/{uid}` → `work_item.customer` and `customer`) gains `phone_on_sheet` and `phone_override`. `phone_e164` and `phone_on_file` read the override first, and `phone_masked` is unchanged.

**Pins:**
- 0 lines moved: `test_journey_rebuild.py:63` and `:65`, `test_fixture_honesty.py:134,139`, `test_round5_data_flow.py:544-550`, `test_round4.py:775`, `test_audit_coverage.py`.
- Measured green in scratch with this task applied: `test_journey_rebuild`, `test_fixture_honesty`, `test_audit_coverage`, `test_payment_status_adjust` and `test_contact_notes` (93 passed), plus `test_round5_data_flow -k r5f01 or r71_7` and `test_round4 -k f3_the_closed_rows or f2_the_export` (4 passed).
- Full backend with no database: 959 passed, 0 failed. No screen changes, so no density figure.

- [ ] **Step 1: Confirm the base**

Run: `git log --oneline -8 && grep -rn "customer_contact\|PHONE_SET\|DEBT-COL-046[3-4]" backend/app backend/tests`
Expected: HEAD `91b8519` or later; grep empty. If another cluster already took DEBT-COL-0463/0464, take the next free pair and use it in the test below too.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_customer_phone.py
"""A phone number a person enters for a customer — Feedback Round 1 / WP9 (design F9 (a)).

Any role may set it, with a reason; it is audited PHONE_SET with "set"/"cleared" and
never the number; every read (the work item, the case detail) serves it first; the
sheet's masked string is never touched (test_journey_rebuild.py:63).
"""
import contextvars
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import audit_store, customer_contact, db, migrate
from app.cases import CaseError
from app.main import app

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"}


def _placeholder_customer():
    """A sheet customer whose import carried no phone (159 of 212)."""
    rows = client.get("/v1/workbook").json()["rows"]
    return next(r["customer"]["uid"] for r in rows
                if r["customer"]["phone_on_file"] is False and r["case"]["payment_status"] != "CLOSED")


def _latest_audit():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _post(uid, body):
    return client.post("/v1/cases/by-customer/%s/phone" % uid, headers=OFFICER, json=body)


# --- the shape rule --------------------------------------------------------------------

@pytest.mark.parametrize("raw, e164, kind, shown", [
    ("0812345678", "+66812345678", "MOBILE", "081-234-5678"),
    ("081-234-5678", "+66812345678", "MOBILE", "081-234-5678"),
    ("+66 81 234 5678", "+66812345678", "MOBILE", "081-234-5678"),
    ("66912345678", "+66912345678", "MOBILE", "091-234-5678"),
    ("06.1234.5678", "+66612345678", "MOBILE", "061-234-5678"),
    ("(02) 123-4567", "+6621234567", "LANDLINE", "02-123-4567"),
    ("053123456", "+6653123456", "LANDLINE", "053-123-456"),
    ("+6674123456", "+6674123456", "LANDLINE", "074-123-456"),
])
def test_a_thai_mobile_or_landline_is_normalised_to_e164(raw, e164, kind, shown):
    assert customer_contact.normalise(raw) == (e164, kind)
    assert customer_contact.display(e164, kind) == shown


@pytest.mark.parametrize("raw", ["12345", "+14155552671", "0112345678", "08123456789", "812345678",
                                 "0812345abc", "0012345678", ""])
def test_anything_else_is_refused_without_echoing_what_was_typed(raw):
    with pytest.raises(CaseError) as caught:
        customer_contact.normalise(raw)
    assert caught.value.code == "phone_invalid"
    assert caught.value.extra["pointer"] == "/phone"
    if raw:
        assert raw not in caught.value.detail and raw not in caught.value.message_th


# --- the route and every read -----------------------------------------------------------

def test_a_person_sets_a_number_and_every_read_serves_it_first():
    uid = _placeholder_customer()
    r = _post(uid, {"phone": "081-234-5678", "reason": "ลูกค้าให้เบอร์ทางไลน์"})
    assert r.status_code == 200, r.json()
    served = r.json()["customer"]
    assert served["uid"] == uid
    assert served["phone_e164"] == "+66812345678" and served["phone_on_file"] is True
    assert served["phone_on_sheet"] is False and served["phone_masked"] == "xxx-xxx-xxxx"
    assert served["phone_override"] == {
        "phone_e164": "+66812345678", "display": "081-234-5678", "kind": "MOBILE", "set_by": "thip",
        "set_at": served["phone_override"]["set_at"], "reason": "ลูกค้าให้เบอร์ทางไลน์", "durable": False,
        "note_th": customer_contact.NOT_DURABLE_TH}
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    for customer in (detail["work_item"]["customer"], detail["customer"]):
        assert customer["phone_e164"] == "+66812345678" and customer["phone_on_file"] is True
        assert "x" in customer["phone_masked"]
    row = next(r for r in client.get("/v1/workbook").json()["rows"] if r["customer"]["uid"] == uid)
    assert row["customer"]["phone_override"]["display"] == "081-234-5678"
    listed = [i for i in client.get("/v1/working-list").json()["items"] if i["customer"]["uid"] == uid]
    assert all(i["customer"]["phone_e164"] == "+66812345678" for i in listed)


def test_a_customer_nobody_touched_serves_exactly_what_the_import_said():
    uid = _placeholder_customer()
    customer = client.get("/v1/cases/by-customer/%s" % uid).json()["work_item"]["customer"]
    assert customer["phone_override"] is None and customer["phone_e164"] is None
    assert customer["phone_on_file"] is False and customer["phone_on_sheet"] is False


def test_the_audit_row_says_set_and_never_carries_the_number():
    uid = _placeholder_customer()
    assert _post(uid, {"phone": "0812345678", "reason": "โทรเข้ามาจากเบอร์ 081-234-5678 วันที่ 2026-10-23"}).status_code == 200
    entry = _latest_audit()
    assert entry["act"] == "PHONE_SET" and (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)
    assert entry["detail"]["phone"] == "set" and entry["detail"]["kind"] == "MOBILE"
    assert entry["detail"]["reason"] == "โทรเข้ามาจากเบอร์ [ตัดเบอร์ออก] วันที่ 2026-10-23"
    flat = json.dumps(entry, ensure_ascii=False)
    for fragment in ("0812345678", "812345678", "234-5678", "+66"):
        assert fragment not in flat


def test_refusals_name_the_field_and_write_nothing():
    uid = _placeholder_customer()
    no_reason = _post(uid, {"phone": "0812345678", "reason": "  "})
    assert (no_reason.status_code, no_reason.json()["code"]) == (422, "reason_required")
    assert no_reason.json()["errors"][0]["pointer"] == "/reason"
    bad = _post(uid, {"phone": "12345", "reason": "x"})
    assert (bad.status_code, bad.json()["code"], bad.json()["error_id"]) == (422, "phone_invalid", "DEBT-COL-0463")
    assert bad.json()["errors"][0]["pointer"] == "/phone" and bad.json()["message_th"] == customer_contact.INVALID_TH
    nothing_to_clear = _post(uid, {"phone": None, "reason": "x"})
    assert (nothing_to_clear.status_code, nothing_to_clear.json()["code"]) == (409, "phone_unchanged")
    assert customer_contact._HISTORY == []
    assert _post(uid, {"phone": "0812345678", "reason": "ใหม่"}).status_code == 200
    same = _post(uid, {"phone": "+66 81 234 5678", "reason": "ซ้ำ"})
    assert (same.status_code, same.json()["code"], same.json()["error_id"]) == (409, "phone_unchanged", "DEBT-COL-0464")
    assert len(customer_contact._HISTORY) == 1
    assert _post("no-such-customer", {"phone": "0812345678", "reason": "x"}).status_code == 404


def test_a_new_number_replaces_the_old_and_clearing_puts_the_import_answer_back():
    uid = _placeholder_customer()
    assert _post(uid, {"phone": "0812345678", "reason": "แรก"}).status_code == 200
    assert _post(uid, {"phone": "021234567", "reason": "เบอร์บ้าน"}).json()["customer"]["phone_override"]["kind"] == "LANDLINE"
    cleared = _post(uid, {"phone": "", "reason": "ลูกค้าขอให้ลบ"})
    assert cleared.status_code == 200
    served = cleared.json()["customer"]
    assert served["phone_override"] is None and served["phone_e164"] is None and served["phone_on_file"] is False
    assert _latest_audit()["detail"]["phone"] == "cleared"
    assert [(r["phone_e164"], r["active"]) for r in customer_contact._HISTORY] == [
        ("+66812345678", False), ("+6621234567", False), (None, False)]


def test_a_pre_install_case_serves_the_same_phone_keys():
    from app.config import settings
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    item = next(r for r in rows if not r["released_at"] and not r["has_case"])
    client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"receipt_ref": "slip-y", "amount": "5000"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], json={"confirmed_on": str(settings.business_date)})
    assert client.post("/v1/pipeline/%s:release" % item["uid"], json={}, headers=OFFICER).status_code == 201
    uid = item["customer_uid"]
    assert _post(uid, {"phone": "021234567", "reason": "ก่อนติดตั้ง"}).status_code == 200
    customer = client.get("/v1/cases/by-customer/%s" % uid).json()["customer"]
    assert customer["phone_e164"] == "+6621234567" and customer["phone_override"]["display"] == "02-123-4567"
    assert customer["phone_masked"] is None and customer["phone_on_sheet"] is False


def test_any_role_may_set_it():
    uid = _placeholder_customer()
    for n, role in enumerate(("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")):
        r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": role},
                        json={"phone": "08123456%02d" % n, "reason": role})
        assert r.status_code == 200, (role, r.json())


# --- one read per request -----------------------------------------------------------------

def test_the_table_is_read_once_per_request_not_once_per_row(monkeypatch):
    loads = []
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(customer_contact, "_load_active", lambda: loads.append(1) or {})

    def one_request():
        for n in range(212):
            customer_contact.active_for("cu-%d" % n)

    contextvars.copy_context().run(one_request)
    contextvars.copy_context().run(one_request)
    assert len(loads) == 2


def test_a_failed_write_never_carries_the_number_into_the_error(monkeypatch):
    """SQLAlchemy puts the bound parameters in its message, and an unhandled error's
    traceback is logged — so the write re-raises by class name, unchained."""
    from sqlalchemy.exc import IntegrityError

    class Refusing:
        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            if params and "p" in params:
                raise IntegrityError(str(statement), params, Exception("duplicate key"))

        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: Refusing())
    monkeypatch.setattr(customer_contact, "_load_active", lambda: {})
    with pytest.raises(RuntimeError) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-x", "0812345678", "thip", "x")
    assert "812345678" not in str(caught.value) and "IntegrityError" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


# --- durable ---------------------------------------------------------------------------

def test_the_number_is_durable_in_records_customer_contact(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    try:
        first = contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", "0812345678", "thip", "แรก")
        assert first["durable"] is True and "note_th" not in first
        again = contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", "0898765432", "noon", "เปลี่ยน")
        assert again["phone_e164"] == "+66898765432" and again["set_by"] == "noon"
        assert contextvars.copy_context().run(customer_contact.active_for, "cu-pg")["display"] == "089-876-5432"
        contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", None, "thip", "ลบ")
        rows = pg_conn.execute(text("select phone_e164, active, reason from records.customer_contact "
                                    "where customer_uid = 'cu-pg' order by uid")).fetchall()
        assert [tuple(r) for r in rows] == [("+66812345678", False, "แรก"), ("+66898765432", False, "เปลี่ยน"),
                                           (None, False, "ลบ")]
        assert contextvars.copy_context().run(customer_contact.active_for, "cu-pg") is None
    finally:
        # pg_conn's teardown truncates only landing and app — records is cleaned here.
        pg_conn.execute(text("delete from records.customer_contact"))
        pg_conn.commit()
        engine.dispose()
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd backend && VOLT_TEST_PG_URL="postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data" .venv/bin/python -m pytest tests/test_customer_phone.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'customer_contact' from 'app'`.

- [ ] **Step 4: Implement — the table**

`backend/app/schema.sql`, appended after line 274:

```sql

-- Feedback Round 1 / WP9 (design F9 (a)): a phone number a person entered for a
-- customer, with who, when and why. PDPA: the only table that holds one — never an
-- audit detail, a log line or an export. Every set or clear is a new row; the one
-- ACTIVE row per customer is the number served. A clear is a row with no number and
-- active = false, so the history keeps who removed it and why.
CREATE TABLE IF NOT EXISTS records.customer_contact (
    uid           bigserial   PRIMARY KEY,
    customer_uid  text        NOT NULL,
    phone_e164    text        CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+66[0-9]{8,9}$'),
    kind          text        CHECK (kind IS NULL OR kind IN ('MOBILE','LANDLINE')),
    set_by        text        NOT NULL,
    set_at        timestamptz NOT NULL DEFAULT now(),
    reason        text        NOT NULL,
    active        boolean     NOT NULL DEFAULT true,
    CHECK (NOT active OR phone_e164 IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS customer_contact_active_idx
    ON records.customer_contact (customer_uid) WHERE active;
```

(`migrate.statements()` tracks single-quoted literals, so the `$` in the regex is not read as a dollar-quote. `text()` binds only `:name`, and there is no colon in the block.)

- [ ] **Step 5: Implement — `backend/app/customer_contact.py`**

```python
"""A phone number a person enters for a customer — Feedback Round 1 / WP9 (design F9 (a)).

The sheet import masked every real number (C5 / REQ-INT-030), so `phone_e164` is null
on 206 of 212 customers and the dial buttons never dial. F9 (a), approved 2026-09-15:
any officer may store a real number, with a reason, audited. Staging is in Singapore;
the PDPA flag stands, so this module is the ONE place a person-entered number lives:

  - records.customer_contact when a database is configured (durable, survives a
    deploy); a process dict labelled not-durable when it is not — the same three-state
    seam db.py and attachments/store.py state. Configured but unreachable raises
    db.DatabaseUnreachable and is never caught to fall back.
  - never in a log line, never in an audit detail (that says "set" or "cleared"),
    never in a case event, never in a CSV export. A reason that quotes a number has
    the number cut out of the AUDIT copy; the records row keeps the reason as typed.

Reads are served per request: `active_for` loads every active row ONCE per request
(one SELECT, memoised in a ContextVar that dies with the request) because
routers/journey._work_item calls it per row — 212 times on /v1/today.
"""
import re
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .cases import CaseError

NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — เบอร์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
KINDS = ("MOBILE", "LANDLINE")

_MEMORY = {}          # customer_uid -> the active row (no database configured)
_HISTORY = []         # every set/cleared row, oldest first (no database configured)
_ACTIVE = ContextVar("customer_contact_active", default=None)

_SEPARATORS = re.compile(r"[\s\-.()]")
_MOBILE = re.compile(r"^0[689]\d{8}$")
_LANDLINE = re.compile(r"^0[2-57]\d{7}$")
# A run of digits with phone separators inside it. Nine or more digits is a phone
# number (a landline has nine); a date (eight digits) or an amount is left alone.
_DIGIT_RUN = re.compile(r"\+?\d[\d\s\-.()]*\d")
INVALID_TH = "เบอร์ต้องเป็นมือถือไทย 10 หลัก (ขึ้นต้น 06 08 09) หรือเบอร์บ้าน 9 หลัก (ขึ้นต้น 02–07) จะใส่ +66 นำหน้าก็ได้"


def reset():
    """Test isolation (tests/conftest.py): the memory store is per process."""
    _MEMORY.clear()
    del _HISTORY[:]
    _ACTIVE.set(None)


def _without_numbers(value):
    """The audit copy of a reason: any run of nine or more digits is cut out."""
    return _DIGIT_RUN.sub(lambda m: "[ตัดเบอร์ออก]" if sum(ch.isdigit() for ch in m.group(0)) >= 9 else m.group(0), value)


def normalise(raw):
    """(e164, kind) for a Thai mobile or landline number, else CaseError phone_invalid.

    Accepts 0812345678, 081-234-5678, +66 81 234 5678, 66812345678, (02) 123-4567.
    The refusal never echoes what was typed.
    """
    compact = _SEPARATORS.sub("", str(raw or ""))
    if compact.startswith("+66"):
        national = "0" + compact[3:]
    elif compact.startswith("66") and len(compact) in (10, 11):
        national = "0" + compact[2:]
    else:
        national = compact
    if _MOBILE.match(national):
        kind = "MOBILE"
    elif _LANDLINE.match(national):
        kind = "LANDLINE"
    else:
        raise CaseError("phone_invalid", "Not a Thai mobile (06/08/09, 10 digits) or landline (02-07, 9 digits) number",
                        message_th=INVALID_TH, pointer="/phone")
    return "+66" + national[1:], kind


def display(e164, kind):
    """The number as an officer reads it aloud: 081-234-5678, 02-123-4567, 053-123-456."""
    national = "0" + e164[3:]
    if kind == "MOBILE":
        return "%s-%s-%s" % (national[:3], national[3:6], national[6:])
    if national.startswith("02"):
        return "%s-%s-%s" % (national[:2], national[2:5], national[5:])
    return "%s-%s-%s" % (national[:3], national[3:6], national[6:])


def _public(row, durable):
    at = row.get("set_at")
    rec = {"phone_e164": row["phone_e164"], "display": display(row["phone_e164"], row["kind"]),
           "kind": row["kind"], "set_by": row["set_by"],
           "set_at": at.isoformat() if hasattr(at, "isoformat") else at,
           "reason": row["reason"], "durable": durable}
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
    return rec


def _load_active():
    conn = db.connect()
    try:
        rows = conn.execute(text(
            "select customer_uid, phone_e164, kind, set_by, set_at, reason "
            "from records.customer_contact where active")).mappings().all()
    finally:
        conn.close()
    return {r["customer_uid"]: _public(dict(r), True) for r in rows}


def active_for(customer_uid):
    """The customer's active override as served, or None."""
    if not db.configured():
        row = _MEMORY.get(customer_uid)
        return _public(row, False) if row else None
    active = _ACTIVE.get()
    if active is None:
        active = _load_active()
        _ACTIVE.set(active)
    return active.get(customer_uid)


def phone_fields(customer_uid, customer=None):
    """The phone keys every customer object serves — one definition for the work item,
    the case detail and the phone route. `phone_masked` is never touched
    (test_journey_rebuild.py:63). `phone_on_sheet` keeps the import's own answer
    (R5-F01); `phone_on_file` becomes true when a person entered a number."""
    override = active_for(customer_uid)
    on_sheet = bool(getattr(customer, "phone_on_file", False)) if customer is not None else False
    return {
        "phone_masked": getattr(customer, "phone_masked", None) if customer is not None else None,
        "phone_on_sheet": on_sheet,
        "phone_on_file": bool(override) or on_sheet,
        "phone_e164": override["phone_e164"] if override else (getattr(customer, "phone_e164", None) if customer is not None else None),
        "phone_override": override,
    }


def set_phone(customer_uid, raw, by, reason):
    """Set (raw is a number) or clear (raw is None or blank) the customer's number.

    Order: reason, then shape, then "changes nothing" — all before the audit line and
    the write, so a refusal writes nothing. Returns the new override, or None when
    cleared.
    """
    if not reason or not str(reason).strip():
        raise CaseError("reason_required", "Changing a phone number needs a reason",
                        message_th="ต้องระบุเหตุผลในการแก้ไขเบอร์โทร", pointer="/reason")
    reason = str(reason).strip()
    clearing = raw is None or not str(raw).strip()
    e164, kind = (None, None) if clearing else normalise(raw)
    current = active_for(customer_uid)
    if (clearing and current is None) or (current is not None and current["phone_e164"] == e164):
        raise CaseError("phone_unchanged", "The customer's number already reads that",
                        message_th="เบอร์ของลูกค้าเป็นแบบนี้อยู่แล้ว", pointer="/phone")
    from . import audit
    audit.describe(act="PHONE_SET", subject=("customer", customer_uid),
                   detail={"phone": "cleared" if clearing else "set", "kind": kind,
                           "reason": _without_numbers(reason)})
    if not db.configured():
        row = {"customer_uid": customer_uid, "phone_e164": e164, "kind": kind, "set_by": by,
               "set_at": datetime.now(timezone.utc), "reason": reason, "active": not clearing}
        previous = _MEMORY.pop(customer_uid, None)
        if previous is not None:
            previous["active"] = False
        _HISTORY.append(row)
        if not clearing:
            _MEMORY[customer_uid] = row
        return active_for(customer_uid)
    conn = db.connect()
    try:
        with conn.begin():
            # One writer per customer at a time: two officers saving at once would
            # otherwise both deactivate nothing and both insert an active row.
            conn.execute(text("select pg_advisory_xact_lock(hashtext(:u))"), {"u": customer_uid})
            conn.execute(text("update records.customer_contact set active = false "
                              "where customer_uid = :u and active"), {"u": customer_uid})
            conn.execute(text("insert into records.customer_contact "
                              "(customer_uid, phone_e164, kind, set_by, reason, active) "
                              "values (:u, :p, :k, :b, :r, :a)"),
                         {"u": customer_uid, "p": e164, "k": kind, "b": by, "r": reason, "a": not clearing})
    except SQLAlchemyError as exc:
        # PDPA: SQLAlchemy's message carries the bound parameters — the number — and an
        # unhandled error's traceback is logged. Re-raised by class name only, unchained.
        raise RuntimeError("records.customer_contact write failed: %s" % type(exc).__name__) from None
    finally:
        conn.close()
    _ACTIVE.set(None)
    return active_for(customer_uid)
```

- [ ] **Step 6: Implement — every read serves it, and the route**

`backend/app/routers/journey.py`: after line 13 (`from .. import clock`) add `from .. import customer_contact`. In `_work_item`, replace lines 210–217:

```python
            "phone_masked": customer.phone_masked,
            # R5-F01: … (the five comment lines stay as they are)
            "phone_on_file": customer.phone_on_file,
            "phone_e164": customer.phone_e164,
```

with:

```python
            # R5-F01: phone_masked alone cannot say whether this is a real mask or the
            # "no number on file" placeholder — 159 of 212 rows serve the literal
            # string "xxx-xxx-xxxx" for both. This is the one shared place that builds
            # the customer object for /v1/today, /v1/workbook, /v1/working-list and
            # /v1/cases/by-customer/{uid} alike, so one field here reaches all four.
            # Feedback Round 1 / WP9 (F9 (a)): a number a person entered wins
            # phone_e164 and makes phone_on_file true; phone_masked is untouched and
            # phone_on_sheet keeps the import's own answer (customer_contact.py).
            **customer_contact.phone_fields(customer.uid, customer),
```

`backend/app/routers/today.py`:
- After line 9 (`from .. import clock`) add `from .. import customer_contact`.
- In `problem_from`'s mapping, after the `attachment_unknown` entry (lines 91–92), add:

```python
        # Feedback Round 1 / WP9 (F9 (a)): a person-entered phone number.
        "phone_invalid": (422, "DEBT-COL-0463", "Not a Thai phone number", customer_contact.INVALID_TH),
        "phone_unchanged": (409, "DEBT-COL-0464", "The number already reads that", "เบอร์ของลูกค้าเป็นแบบนี้อยู่แล้ว"),
```

Line 694 (`_pre_install_case_detail`): replace `"phone_masked": None, "phone_e164": None, "line_id": None,` with `**customer_contact.phone_fields(customer_uid), "line_id": None,`.

Line 835 (`case_detail`): replace `"phone_masked": customer.phone_masked, "phone_e164": customer.phone_e164, "line_id": customer.line_id,` with:

```python
                     # WP9: the same phone keys the work item's customer serves (R5-F01's
                     # escalation — the two objects used to disagree on phone_on_file).
                     **customer_contact.phone_fields(customer.uid, customer), "line_id": customer.line_id,
```

Before line 1063 (`@router.post("/v1/cases/by-customer/{customer_uid}/npl-type")`), after `set_payment_status`, insert:

```python
@router.post("/v1/cases/by-customer/{customer_uid}/phone")
def set_customer_phone(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """Feedback Round 1 / WP9 (design F9 (a)): a real phone number for the customer,
    entered by any role with a reason, audited PHONE_SET ("set"/"cleared", never the
    number). Body {"phone": "081-234-5678" | null, "reason": "..."}; a null or blank
    phone clears it. Answers the customer's phone keys exactly as every read serves
    them, so the screen shows the server's own formatting."""
    cs = cases_domain.for_current()
    _case_or_404(cs, customer_uid)
    try:
        customer_contact.set_phone(customer_uid, body.get("phone"), by=who(body, x_volt_officer),
                                   reason=body.get("reason"))
    except CaseError as exc:
        raise problem_from(exc)
    fields = customer_contact.phone_fields(customer_uid, journey.customer_by_uid(customer_uid))
    return {"customer": {"uid": customer_uid, **fields}}
```

`backend/tests/conftest.py`, after line 52 (`attachments_store.reset()`):

```python
    from app import customer_contact
    customer_contact.reset()          # WP9: person-entered phone numbers, memory store
```

- [ ] **Step 7: Run the tests, the pins, then the suite**

Run: `cd backend && VOLT_TEST_PG_URL="postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data" .venv/bin/python -m pytest tests/test_customer_phone.py -v`
Expected: 26 passed. The DB-backed test passes, not skips, because the URL is set.

Run: `cd backend && VOLT_TEST_PG_URL=… .venv/bin/python -m pytest tests/test_journey_rebuild.py tests/test_fixture_honesty.py tests/test_audit_coverage.py tests/test_payment_status_adjust.py tests/test_contact_notes.py tests/test_round5_data_flow.py tests/test_round4.py`
Expected: PASS, with `test_journey_rebuild.py:63-65`, `test_round5_data_flow.py:544-550` and `test_round4.py:775` untouched.

Run: `cd backend && VOLT_TEST_PG_URL=… .venv/bin/python -m pytest --continue-on-collection-errors`
Expected: PASS at the Task-start baseline + 26. **Paste the count.**

- [ ] **Step 8: Black-box**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED. e2e stays 31 of 31, because the new keys are additive and nested. **Paste the three counts.**

- [ ] **Step 9: Commit**

```bash
cat > "$SCRATCH/b6-commit.txt" <<'MSG'
feat(case): a durable, audited phone number per customer — records.customer_contact, POST .../phone, served first on every read

Design WP9 / F9 (a): any role, a reason required, Thai mobile or landline normalised to
E.164, audited PHONE_SET with "set"/"cleared" and never the number (a number typed into
the reason is cut from the audit copy; a failed write re-raises unchained). The table is
read once per request. phone_masked is untouched; phone_on_sheet keeps the import's
answer; phone_e164 and phone_on_file read the override first. Error ids DEBT-COL-0463/0464.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
MSG
git add backend/app/customer_contact.py backend/tests/test_customer_phone.py
git commit -F "$SCRATCH/b6-commit.txt" -- backend/app/customer_contact.py backend/tests/test_customer_phone.py backend/app/schema.sql backend/app/routers/journey.py backend/app/routers/today.py backend/tests/conftest.py
```

---

### Task B7a: `PhoneOnCase` — the number, copy, edit with a reason, the sheet mask beside it

**Files:**
- Create: `frontend/src/components/PhoneOnCase.jsx`, `frontend/src/components/PhoneOnCase.test.jsx`
- Modify: `frontend/src/api.js` (one binding after line 246)
- Modify: `frontend/src/i18n-today.js` (15 keys at the end of `TODAY_EN` and `TODAY_TH`, after B5's)
- Modify: `frontend/src/today.css` (one rule after B5's `.cs-calc__item`)

**Interfaces:**
- Consumes: B6's served customer keys `phone_override {phone_e164, display, kind, set_by, set_at, reason, durable, note_th?}`, `phone_on_sheet`, `phone_on_file`, `phone_masked`. It also consumes B6's refusal shape (`errors[0].message_th`), read through `problem.js`'s `refusalText`.
- Produces:
  - `api.setCustomerPhone(customerUid, { phone, reason, by }) -> Promise<{ customer }>` (POST).
  - `<PhoneOnCase customer={…} onSave={async (payload) => res | throw} prefix="case"|"cd" />`. It renders a fragment, so it fits a flex row with no wrapper element.
  - Test ids, all `${prefix}-`: `phone-number`, `phone-copy`, `phone-copied`, `phone-edit`, `phone-sheet`, `phone-not-durable`, `phone-form`, `phone-set-by`, `phone-clear`, `phone-save-why`, `phone-problem`. Input ids: `${prefix}-phone-input`, `${prefix}-phone-reason`.
  - i18n keys, EN / TH:
    - `case.phone.add` "Add a number" / "เพิ่มเบอร์"
    - `case.phone.edit` "Change the number" / "แก้ไขเบอร์"
    - `case.phone.copy` "Copy the number" / "คัดลอกเบอร์"
    - `case.phone.copied` "Copied" / "คัดลอกแล้ว"
    - `case.phone.copyFailed` "Could not copy — select the number and press Ctrl+C" / "คัดลอกไม่ได้ — เลือกเบอร์แล้วกด Ctrl+C"
    - `case.phone.sheet` "sheet says {mask}" / "ชีตระบุ {mask}"
    - `case.phone.label` "Phone number" / "เบอร์โทร"
    - `case.phone.reason` "Why is the number changing?" / "เหตุผลที่แก้ไขเบอร์"
    - `case.phone.save` "Save the number" / "บันทึกเบอร์"
    - `case.phone.clear` "Remove the number" / "ลบเบอร์"
    - `case.phone.saveWhy` "Type the number and a reason first" / "กรอกเบอร์และเหตุผลก่อนบันทึก"
    - `case.phone.hint` "Thai mobile (06, 08, 09 — 10 digits) or landline (02–07 — 9 digits); +66 is fine" / "มือถือ 10 หลัก (06 08 09) หรือเบอร์บ้าน 9 หลัก (02–07) ใส่ +66 ได้"
    - `case.phone.setBy` "set by {who} · {reason}" / "บันทึกโดย {who} · {reason}"
    - `case.phone.notDurable` "No database — this number is kept in memory and is lost on restart" / "ไม่มีฐานข้อมูล — เบอร์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
    - `case.phone.saved` "Phone number saved" / "บันทึกเบอร์โทรแล้ว"

**Pins:** 0 (a new component; nothing mounts it until B7b). No density change.

- [ ] **Step 1: Confirm the key names are free**

Run: `grep -n "'case\.phone\.\|setCustomerPhone" frontend/src/i18n-*.js frontend/src/api.js`
Expected: nothing.

- [ ] **Step 2: Write the failing test**

```jsx
// frontend/src/components/PhoneOnCase.test.jsx
// Feedback Round 1 / WP9 (design F9 (a)): the phone number on the case, copyable and
// editable with a reason. Everything drawn is served; the client only trims.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'
import { PhoneOnCase } from './PhoneOnCase.jsx'

const OVERRIDE = { phone_e164: '+66812345678', display: '081-234-5678', kind: 'MOBILE', set_by: 'thip',
                   set_at: '2026-10-23T09:15:00+07:00', reason: 'ลูกค้าให้เบอร์ใหม่', durable: true }
const WITH = { uid: 'cu-1', phone_masked: '08x-xxx-4810', phone_on_sheet: true, phone_on_file: true,
               phone_e164: '+66812345678', phone_override: OVERRIDE }
const SHEET_ONLY = { uid: 'cu-1', phone_masked: '08x-xxx-4810', phone_on_sheet: true, phone_on_file: true,
                     phone_e164: null, phone_override: null }
const NOTHING = { uid: 'cu-1', phone_masked: 'xxx-xxx-xxxx', phone_on_sheet: false, phone_on_file: false,
                  phone_e164: null, phone_override: null }

function withClipboard(writeText) {
  Object.defineProperty(window.navigator, 'clipboard', { value: { writeText }, configurable: true })
}

beforeEach(() => withClipboard(vi.fn(() => Promise.resolve())))
afterEach(() => { delete window.navigator.clipboard })

describe('PhoneOnCase — at rest', () => {
  it('shows the number the server formatted, the sheet mask beside it, copy and edit', () => {
    renderIn('th', <PhoneOnCase customer={WITH} onSave={vi.fn()} />)
    expect(screen.getByTestId('case-phone-number')).toHaveTextContent('081-234-5678')
    expect(screen.getByTestId('case-phone-sheet')).toHaveTextContent('ชีตระบุ 08x-xxx-4810')
    expect(screen.getByTestId('case-phone-copy')).toHaveTextContent('คัดลอกเบอร์')
    expect(screen.getByTestId('case-phone-edit')).toHaveTextContent('แก้ไขเบอร์')
  })

  it('without a number: what the sheet says, or that there is none, one add control, no copy', () => {
    const { unmount } = renderIn('th', <PhoneOnCase customer={SHEET_ONLY} onSave={vi.fn()} />)
    expect(screen.getByTestId('case-phone-sheet')).toHaveTextContent('ชีตระบุ 08x-xxx-4810')
    expect(screen.queryByTestId('case-phone-copy')).toBeNull()
    expect(screen.getByTestId('case-phone-edit')).toHaveTextContent('เพิ่มเบอร์')
    unmount()
    renderIn('th', <PhoneOnCase customer={NOTHING} onSave={vi.fn()} />)
    expect(screen.getByText('ไม่มีเบอร์ในระบบ')).toBeInTheDocument()
    expect(screen.queryByText('xxx-xxx-xxxx')).toBeNull()
  })

  it('says a number kept without a database is lost on restart', () => {
    renderIn('th', <PhoneOnCase customer={{ ...WITH, phone_override: { ...OVERRIDE, durable: false, note_th: 'ไม่มีฐานข้อมูล — หายเมื่อรีสตาร์ท' } }} onSave={vi.fn()} />)
    expect(screen.getByTestId('case-phone-not-durable')).toHaveTextContent('หายเมื่อรีสตาร์ท')
  })

  it('offers no copy button where the browser has no clipboard', () => {
    delete window.navigator.clipboard
    renderIn('th', <PhoneOnCase customer={WITH} onSave={vi.fn()} />)
    expect(screen.queryByTestId('case-phone-copy')).toBeNull()
    expect(screen.getByTestId('case-phone-number')).toHaveClass('td-mono--select')
  })
})

describe('PhoneOnCase — copy', () => {
  it('copies the number as it is shown, and says so', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    withClipboard(writeText)
    renderIn('th', <PhoneOnCase customer={WITH} onSave={vi.fn()} />)
    fireEvent.click(screen.getByTestId('case-phone-copy'))
    expect(await screen.findByTestId('case-phone-copied')).toHaveTextContent('คัดลอกแล้ว')
    expect(writeText).toHaveBeenCalledWith('081-234-5678')
  })

  it('says when the copy failed, never silently', async () => {
    withClipboard(vi.fn(() => Promise.reject(new Error('denied'))))
    renderIn('th', <PhoneOnCase customer={WITH} onSave={vi.fn()} />)
    fireEvent.click(screen.getByTestId('case-phone-copy'))
    expect(await screen.findByTestId('case-phone-copied')).toHaveTextContent('คัดลอกไม่ได้')
  })
})

describe('PhoneOnCase — edit', () => {
  it('will not save without a number and a reason, and says why', () => {
    const onSave = vi.fn()
    renderIn('th', <PhoneOnCase customer={NOTHING} onSave={onSave} />)
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    expect(within(form).getByRole('button', { name: 'บันทึกเบอร์' })).toBeDisabled()
    expect(within(form).getByTestId('case-phone-save-why')).toHaveTextContent('กรอกเบอร์และเหตุผลก่อนบันทึก')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: '0812345678' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: '   ' } })
    expect(within(form).getByRole('button', { name: 'บันทึกเบอร์' })).toBeDisabled()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('sends the trimmed number and reason, and closes when the server accepts', async () => {
    const onSave = vi.fn(() => Promise.resolve({ customer: WITH }))
    renderIn('th', <PhoneOnCase customer={NOTHING} onSave={onSave} />)
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: ' 081-234-5678 ' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: ' ลูกค้าให้ทางไลน์ ' } })
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกเบอร์' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ phone: '081-234-5678', reason: 'ลูกค้าให้ทางไลน์' }))
    await waitFor(() => expect(screen.queryByTestId('case-phone-form')).toBeNull())
  })

  it('keeps the form open and prints the server\'s own refusal', async () => {
    const problem = { code: 'phone_invalid', message_th: 'ข้อความทั่วไป',
                      errors: [{ pointer: '/phone', code: 'phone_invalid', message_th: 'เบอร์ต้องเป็นมือถือไทย 10 หลัก' }] }
    const onSave = vi.fn(() => Promise.reject(Object.assign(new Error('x'), { problem })))
    renderIn('th', <PhoneOnCase customer={NOTHING} onSave={onSave} />)
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: '12345' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ทดสอบ' } })
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกเบอร์' }))
    expect(await within(form).findByTestId('case-phone-problem')).toHaveTextContent('เบอร์ต้องเป็นมือถือไทย 10 หลัก')
    expect(screen.getByTestId('case-phone-form')).toBeInTheDocument()
  })

  it('clears a number with a reason only, and shows who set it and why', async () => {
    const onSave = vi.fn(() => Promise.resolve({ customer: NOTHING }))
    renderIn('th', <PhoneOnCase customer={WITH} onSave={onSave} />)
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    expect(within(form).getByTestId('case-phone-set-by')).toHaveTextContent('บันทึกโดย thip · ลูกค้าให้เบอร์ใหม่')
    expect(within(form).getByTestId('case-phone-clear')).toBeDisabled()
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ลูกค้าขอให้ลบ' } })
    fireEvent.click(within(form).getByTestId('case-phone-clear'))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ phone: null, reason: 'ลูกค้าขอให้ลบ' }))
  })

  it('prefixes every id so the header and the dialog can share a page', () => {
    const { container } = renderIn('th', (
      <>
        <PhoneOnCase customer={WITH} onSave={vi.fn()} prefix="case" />
        <PhoneOnCase customer={WITH} onSave={vi.fn()} prefix="cd" />
      </>
    ))
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    fireEvent.click(screen.getByTestId('cd-phone-edit'))
    expect(container.querySelectorAll('#case-phone-input')).toHaveLength(1)
    expect(container.querySelectorAll('#cd-phone-input')).toHaveLength(1)
  })
})
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/components/PhoneOnCase.test.jsx`
Expected: FAIL — cannot resolve `./PhoneOnCase.jsx`.

- [ ] **Step 4: Implement the component**

```jsx
// frontend/src/components/PhoneOnCase.jsx
import { useEffect, useRef, useState } from 'react'
import { usePrefs } from '../prefs.jsx'
import { refusalText } from '../problem.js'

// Feedback Round 1 / WP9 (design F9 (a)): a phone number a person enters, per
// customer, with a reason — stored by the server in records.customer_contact and
// audited as PHONE_SET with "set"/"cleared", never the number. Everything drawn here
// is served on the customer object (`phone_override`, `phone_on_sheet`,
// `phone_masked`, `phone_on_file`); the number is formatted by the server
// (`phone_override.display`) and validated by the server. The client only trims.
//
// One component, two places: the case header (prefix "case") and the Save-contact
// dialog (prefix "cd"), which can both be in the DOM at once — hence the prefix on
// every id and test id. A fragment, so it sits in either flex row with no wrapper.
export function PhoneOnCase({ customer, onSave, prefix = 'case' }) {
  const { t } = usePrefs()
  const [editing, setEditing] = useState(false)
  const [phone, setPhone] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [copied, setCopied] = useState(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  if (!customer) return null
  const override = customer.phone_override || null
  const canCopy = Boolean(override)
    && typeof navigator !== 'undefined' && typeof navigator.clipboard?.writeText === 'function'

  function open() {
    setEditing((v) => !v)
    setPhone(override ? override.display : '')
    setReason('')
    setProblem(null)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(override.display)
      if (alive.current) setCopied('ok')
    } catch {
      if (alive.current) setCopied('failed')
    }
  }

  async function submit(payload) {
    setBusy(true)
    setProblem(null)
    try {
      await onSave(payload)
      if (!alive.current) return
      setEditing(false)
      setPhone('')
      setReason('')
    } catch (e) {
      if (alive.current) setProblem(e?.problem || { title: String(e?.message || e), code: 'request_failed' })
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const missing = !phone.trim() || !reason.trim()
  return (
    <>
      {override ? (
        <span className="td-mono td-mono--select" data-testid={`${prefix}-phone-number`}>{override.display}</span>
      ) : customer.phone_on_file === false ? (
        // R5-F01: the placeholder "xxx-xxx-xxxx" is not a mask and never renders as one.
        <span className="td-quiet">{t('case.phoneAbsent')}</span>
      ) : (
        <span className="td-quiet" data-testid={`${prefix}-phone-sheet`}>{t('case.phone.sheet', { mask: customer.phone_masked })}</span>
      )}
      {canCopy && (
        <button type="button" className="btn btn--sm btn--quiet" data-testid={`${prefix}-phone-copy`} onClick={copy}>
          {t('case.phone.copy')}
        </button>
      )}
      <button type="button" className="btn btn--sm btn--quiet" data-testid={`${prefix}-phone-edit`}
              aria-expanded={editing} onClick={open}>
        {override ? t('case.phone.edit') : t('case.phone.add')}
      </button>
      {override && customer.phone_on_sheet && customer.phone_masked && (
        <span className="td-quiet" data-testid={`${prefix}-phone-sheet`}>{t('case.phone.sheet', { mask: customer.phone_masked })}</span>
      )}
      {override && override.durable === false && (
        <span className="td-quiet" data-testid={`${prefix}-phone-not-durable`}>{override.note_th || t('case.phone.notDurable')}</span>
      )}
      {copied && (
        <span className="td-quiet" role="status" data-testid={`${prefix}-phone-copied`}>
          {copied === 'ok' ? t('case.phone.copied') : t('case.phone.copyFailed')}
        </span>
      )}
      {editing && (
        <form className="cs-slip cs-phone-form" data-testid={`${prefix}-phone-form`} aria-label={t('case.phone.edit')}
              onSubmit={(e) => { e.preventDefault(); if (!missing) submit({ phone: phone.trim(), reason: reason.trim() }) }}>
          {override && (
            <p className="td-quiet" style={{ gridColumn: '1 / -1' }} data-testid={`${prefix}-phone-set-by`}>
              {t('case.phone.setBy', { who: override.set_by, reason: override.reason })}
            </p>
          )}
          <div className="cs-field">
            <label htmlFor={`${prefix}-phone-input`}>{t('case.phone.label')}</label>
            <input id={`${prefix}-phone-input`} type="tel" inputMode="tel" autoComplete="off" value={phone}
                   onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="cs-field">
            <label htmlFor={`${prefix}-phone-reason`}>{t('case.phone.reason')}</label>
            <input id={`${prefix}-phone-reason`} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <p className="td-quiet" style={{ gridColumn: '1 / -1' }}>{t('case.phone.hint')}</p>
          <div className="cs-row">
            <button type="submit" className="btn btn--sm btn--primary" disabled={busy || missing}>{t('case.phone.save')}</button>
            {override && (
              <button type="button" className="btn btn--sm" data-testid={`${prefix}-phone-clear`} disabled={busy || !reason.trim()}
                      onClick={() => submit({ phone: null, reason: reason.trim() })}>
                {t('case.phone.clear')}
              </button>
            )}
            <button type="button" className="btn btn--sm" onClick={() => setEditing(false)}>{t('common.cancel')}</button>
          </div>
          {missing && (
            <span className="td-quiet" style={{ gridColumn: '1 / -1' }} data-testid={`${prefix}-phone-save-why`}>{t('case.phone.saveWhy')}</span>
          )}
          {problem && (
            <p className="cd-hint cd-hint--required" role="alert" style={{ gridColumn: '1 / -1' }} data-testid={`${prefix}-phone-problem`}>
              {refusalText(problem)}
            </p>
          )}
        </form>
      )}
    </>
  )
}
```

(`common.cancel` exists in `i18n-journey.js:294/728`; `case.phoneAbsent` in `i18n-today.js:256/822`.)

- [ ] **Step 5: The binding, the strings, the rule**

`frontend/src/api.js`, after line 246 (`setPaymentStatus: …`):

```js
  // Feedback Round 1 / WP9: a phone number a person enters, with a reason ({ phone, reason, by }).
  setCustomerPhone: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/phone`, payload),
```

`frontend/src/i18n-today.js`, at the end of `TODAY_EN` (after B5's `case.calc.*` block):

```js
  // Feedback Round 1 / WP9 (design F9 (a)): a phone number a person enters, with a reason.
  'case.phone.add': 'Add a number',
  'case.phone.edit': 'Change the number',
  'case.phone.copy': 'Copy the number',
  'case.phone.copied': 'Copied',
  'case.phone.copyFailed': 'Could not copy — select the number and press Ctrl+C',
  'case.phone.sheet': 'sheet says {mask}',
  'case.phone.label': 'Phone number',
  'case.phone.reason': 'Why is the number changing?',
  'case.phone.save': 'Save the number',
  'case.phone.clear': 'Remove the number',
  'case.phone.saveWhy': 'Type the number and a reason first',
  'case.phone.hint': 'Thai mobile (06, 08, 09 — 10 digits) or landline (02–07 — 9 digits); +66 is fine',
  'case.phone.setBy': 'set by {who} · {reason}',
  'case.phone.notDurable': 'No database — this number is kept in memory and is lost on restart',
  'case.phone.saved': 'Phone number saved',
```

At the end of `TODAY_TH`:

```js
  'case.phone.add': 'เพิ่มเบอร์',
  'case.phone.edit': 'แก้ไขเบอร์',
  'case.phone.copy': 'คัดลอกเบอร์',
  'case.phone.copied': 'คัดลอกแล้ว',
  'case.phone.copyFailed': 'คัดลอกไม่ได้ — เลือกเบอร์แล้วกด Ctrl+C',
  'case.phone.sheet': 'ชีตระบุ {mask}',
  'case.phone.label': 'เบอร์โทร',
  'case.phone.reason': 'เหตุผลที่แก้ไขเบอร์',
  'case.phone.save': 'บันทึกเบอร์',
  'case.phone.clear': 'ลบเบอร์',
  'case.phone.saveWhy': 'กรอกเบอร์และเหตุผลก่อนบันทึก',
  'case.phone.hint': 'มือถือ 10 หลัก (06 08 09) หรือเบอร์บ้าน 9 หลัก (02–07) ใส่ +66 ได้',
  'case.phone.setBy': 'บันทึกโดย {who} · {reason}',
  'case.phone.notDurable': 'ไม่มีฐานข้อมูล — เบอร์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท',
  'case.phone.saved': 'บันทึกเบอร์โทรแล้ว',
```

`frontend/src/today.css`, after B5's `.cs-calc__item` rule:

```css
/* Feedback Round 1 / WP9: the phone form takes its own line inside a wrapping chip row
   (.cs-head__meta on the case, .cd-chips in the dialog); .cs-slip draws the box. */
.cs-phone-form { flex-basis: 100%; }
```

- [ ] **Step 6: Run the test, i18n, the suite**

Run: `cd frontend && npx vitest run src/components/PhoneOnCase.test.jsx src/i18n.test.js src/api.test.js`
Expected: PASS (11 new).

Run: `cd frontend && npx vitest run && npx vite build`
Expected: PASS at the Task-start baseline + 11. **Paste the count.**

- [ ] **Step 7: Commit**

```bash
cat > "$SCRATCH/b7a-commit.txt" <<'MSG'
feat(case): PhoneOnCase — the entered number, copy, edit with a reason, and what the sheet says beside it

Design WP9 / F9 (a). Everything drawn is served (display, provenance, durable); the
server validates; refusals render from errors[0].message_th. api.setCustomerPhone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
MSG
git add frontend/src/components/PhoneOnCase.jsx frontend/src/components/PhoneOnCase.test.jsx
git commit -F "$SCRATCH/b7a-commit.txt" -- frontend/src/components/PhoneOnCase.jsx frontend/src/components/PhoneOnCase.test.jsx frontend/src/api.js frontend/src/i18n-today.js frontend/src/today.css
```

---

### Task B7b: The phone on the case header and in the Save-contact dialog; the dial button uses it

**Files:**
- Modify: `frontend/src/screens/CustomerCase.jsx`:
  - import after line 26
  - `savePhone` after B5's `calcHas`
  - 536–538 (the phone span)
  - 576–577 (`ContactActions` gains `why`)
  - drawer mount near 1872 (`onPhoneSaved`)
- Modify: `frontend/src/components/CaseContactDrawer.jsx`:
  - 16 (import), 254–255 (prop)
  - after 327 (state), after 432 (reset), after 462 (`savePhone`, `shownCustomer`, `dialItem`)
  - 900–903 (the phone span), 909 (`ContactActions item`)
- Test: `frontend/src/screens/CustomerCase.phone.test.jsx` (create), `frontend/src/components/CaseContactDrawer.phone.test.jsx` (create)

**Interfaces:**
- Consumes:
  - `PhoneOnCase` and `api.setCustomerPhone` (B7a)
  - B6's served keys on `work_item.customer` and `customer`
  - `ContactActions({ item, why })` at `CaseContactDrawer.jsx:186`, where `why` defaults true
- Produces:
  - Case header: `case-phone-*` test ids inside `header.cs-head`. The dial `tel:` link appears when `work_item.customer.phone_e164` is served. `contact-disabled-why` is absent when there is no phone, and still reads "ไม่มี LINE ID" when a phone is served without a LINE id.
  - Dialog: `cd-phone-*` test ids inside `.cd-chips`, and the dial link in `.cd-dial` uses the saved number at once.
  - New optional prop `CaseContactDrawer({ …, onPhoneSaved })`. The case page passes `() => load()`; Today passes nothing and reloads on close as it already does (`Today.jsx:1180`).

**Pins:** 0 lines moved.
- `Today.test.jsx:218-226` and `:238-243`, `CaseContactDrawer.test.jsx:209` and the drawer's 47 tests, `CustomerCase.test.jsx` (46) and `CustomerCase.paymentStatus.test.jsx` (8) all stay green without edits (measured in scratch).
- Density:
  - Before (after B5) the fixtures read 109 / 128, the fixtures with an override 110 / 129, the real header 117 / 136, and the real header with an override 118 / 137.
  - After, measured: 109 / 128, 113 / 132, 117 / 136, 121 / 140.
  - `today-density` stays 31 / 112 / 1,662.
  - The dialog `.cd-head` subtree goes 19 → 20 with no number and 20 → 23 with one.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/screens/CustomerCase.phone.test.jsx
// Feedback Round 1 / WP9 (design F9 (a)): the phone on the case header — copyable,
// editable with a reason, the sheet's mask beside it, and the dial button alive once a
// number is served. ADDED tests; no pinned test is edited.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import CustomerCase from './CustomerCase.jsx'

vi.mock('../api.js', () => ({
  api: {
    caseDetail: vi.fn(), recordLinkSent: vi.fn(), dictionary: vi.fn(), setNextAction: vi.fn(),
    setDcStatus: vi.fn(), setPaymentStatus: vi.fn(), setNplType: vi.fn(), logContact: vi.fn(),
    logCaseContact: vi.fn(), retractContact: vi.fn(), closeCasePtp: vi.fn(), renegotiatePtp: vi.fn(),
    requestReview: vi.fn(), closeCaseIssue: vi.fn(), requestPower: vi.fn(), powerAct: vi.fn(),
    confirmSlip: vi.fn(), setCustomerPhone: vi.fn(),
  },
}))

const Page = () => (
  <MemoryRouter initialEntries={['/customers/cu-1']}>
    <Routes><Route path="/customers/:customerUid" element={<CustomerCase />} /></Routes>
  </MemoryRouter>
)

const OVERRIDE = { phone_e164: '+66812345678', display: '081-234-5678', kind: 'MOBILE', set_by: 'thip',
                   set_at: '2026-10-23T09:15:00+07:00', reason: 'ลูกค้าให้เบอร์ใหม่', durable: true }
const NO_NUMBER = { phone_masked: 'xxx-xxx-xxxx', phone_on_sheet: false, phone_on_file: false, phone_e164: null, phone_override: null }
const A_NUMBER = { phone_masked: '08x-xxx-4810', phone_on_sheet: true, phone_on_file: true,
                   phone_e164: '+66812345678', phone_override: OVERRIDE }

const detail = (phone) => {
  const customer = { uid: 'cu-1', customer_no: '99999000112', display_name: 'ลูกค้าทดสอบ 0187',
                     line_id: null, contract_count: 1, officer: 'nantapol', ...phone }
  return {
    case: {
      uid: 'case-1', customer_uid: 'cu-1', customer_no: '99999000112', volt_id: '99999000112_VOLT', product: 'LEASE',
      officer_uid: 'nantapol', payment_status: 'LATE', payment_status_system: 'LATE', dc_status: 'CONTACT_BACK',
      npl_type: null, next_action: 'CALL', next_action_on: '2026-10-29', last_contact_at: null, last_contact_by: null,
      last_result: null, open_ptp_uid: null, broken_ptp_count: 0, kept_ptp_count: 0, renegotiation_count: 0,
      open_issue_uid: null, power_state: 'ON', power_uid: null, review_uid: null, sheet: {},
    },
    work_item: {
      customer, entity: 'SPV', company_id: 'CO-SPV', aggregate_overdue: '2999.00', aggregate_outstanding: '212928.99',
      oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL', open_ptp: null, contact_lock: { state: 'OPEN' },
    },
    customer: { ...customer, volt_id: '99999000112_VOLT' },
    contracts: [{ uid: 'K-1-L', product: 'LEASE', entity: 'SPV', status: 'PAST_DUE', principal: '176411.76',
                  term_months: 96, first_due: '2024-09-10', paid_through: 25, derivation: {}, fee_state: null }],
    month_grid: [], contact_log: [], ptps: [], issues: [], reviews: [], power: [], sheet_row: {},
    invoices: [], receipts: [], events: [],
  }
}

// Same method as density.test.jsx's census (elements inside a SHUT <details>, less its
// summary, are hidden), copied rather than imported: that file exports nothing.
function visible(container) {
  const closed = [...container.querySelectorAll('details')].filter((d) => !d.hasAttribute('open'))
  const outermost = closed.filter((d) => !closed.some((o) => o !== d && o.contains(d)))
  const hidden = outermost.reduce((n, d) => {
    const summary = d.querySelector(':scope > summary')
    return n + d.querySelectorAll('*').length - (summary ? summary.querySelectorAll('*').length + 1 : 0)
  }, 0)
  return container.querySelectorAll('*').length - hidden
}

async function open(data) {
  api.caseDetail.mockResolvedValue(data)
  const view = renderIn('th', <Page />)
  await screen.findByRole('heading', { level: 1, name: 'ลูกค้าทดสอบ 0187' })
  return view
}

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER')
  setOfficer('thip')
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true })
})

describe('WP9 — the phone on the case header', () => {
  it('shows the entered number, the sheet mask beside it, and dials it', async () => {
    const { container } = await open(detail(A_NUMBER))
    const header = container.querySelector('header.cs-head')
    expect(within(header).getByTestId('case-phone-number')).toHaveTextContent('081-234-5678')
    expect(within(header).getByTestId('case-phone-sheet')).toHaveTextContent('ชีตระบุ 08x-xxx-4810')
    expect(within(header).getByRole('link', { name: 'โทร' })).toHaveAttribute('href', 'tel:+66812345678')
  })

  it('with no number, says so once — beside the add control — and draws no dial button', async () => {
    const { container } = await open(detail(NO_NUMBER))
    const header = container.querySelector('header.cs-head')
    expect(within(header).getByText('ไม่มีเบอร์ในระบบ')).toBeInTheDocument()
    expect(within(header).getByTestId('case-phone-edit')).toHaveTextContent('เพิ่มเบอร์')
    expect(within(header).queryByRole('link', { name: 'โทร' })).toBeNull()
    expect(within(header).queryByTestId('contact-disabled-why')).toBeNull()
  })

  it('still says why LINE is off when there is a number but no LINE id', async () => {
    const { container } = await open(detail(A_NUMBER))
    expect(within(container.querySelector('header.cs-head')).getByTestId('contact-disabled-why'))
      .toHaveTextContent('ไม่มี LINE ID')
  })

  it('saves a number signed by the top-bar identity, then re-reads the case', async () => {
    api.setCustomerPhone.mockResolvedValue({ customer: { uid: 'cu-1', ...A_NUMBER } })
    await open(detail(NO_NUMBER))
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: '081-234-5678' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ลูกค้าให้ทางไลน์' } })
    api.caseDetail.mockResolvedValue(detail(A_NUMBER))
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกเบอร์' }))
    await waitFor(() => expect(api.setCustomerPhone).toHaveBeenCalledWith('cu-1',
      { phone: '081-234-5678', reason: 'ลูกค้าให้ทางไลน์', by: 'thip' }))
    expect(await screen.findByTestId('case-phone-number')).toHaveTextContent('081-234-5678')
    expect(api.caseDetail).toHaveBeenCalledTimes(2)
  })

  it('a number saved in the Save-contact dialog re-reads the case behind it', async () => {
    api.setCustomerPhone.mockResolvedValue({ customer: { uid: 'cu-1', ...A_NUMBER } })
    const { container } = await open(detail(NO_NUMBER))
    fireEvent.click(screen.getAllByRole('button', { name: 'บันทึกการติดต่อ' })[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByTestId('cd-phone-edit'))
    fireEvent.change(within(dialog).getByLabelText('เบอร์โทร'), { target: { value: '0812345678' } })
    fireEvent.change(within(dialog).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ลูกค้าบอกระหว่างคุย' } })
    api.caseDetail.mockResolvedValue(detail(A_NUMBER))
    fireEvent.click(within(dialog).getByRole('button', { name: 'บันทึกเบอร์' }))
    await waitFor(() => expect(api.caseDetail).toHaveBeenCalledTimes(2))
    expect(await within(container.querySelector('header.cs-head')).findByTestId('case-phone-number'))
      .toHaveTextContent('081-234-5678')
  })

  it('prints a refusal beside the form and keeps what was typed', async () => {
    api.setCustomerPhone.mockRejectedValue(Object.assign(new Error('x'), { problem: {
      code: 'phone_invalid', message_th: 'ข้อมูลไม่ถูกต้อง',
      errors: [{ pointer: '/phone', code: 'phone_invalid', message_th: 'เบอร์ต้องเป็นมือถือไทย 10 หลัก' }] } }))
    await open(detail(NO_NUMBER))
    fireEvent.click(screen.getByTestId('case-phone-edit'))
    const form = screen.getByTestId('case-phone-form')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: '12345' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ทดสอบ' } })
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกเบอร์' }))
    expect(await screen.findByTestId('case-phone-problem')).toHaveTextContent('เบอร์ต้องเป็นมือถือไทย 10 หลัก')
    expect(within(form).getByLabelText('เบอร์โทร')).toHaveValue('12345')
  })
})

describe('WP9 — what the phone costs the page (measured, added)', () => {
  // Measured 2026-09-15 on the plan's scratch build: no number = the old one span plus
  // the add control, less the no-phone sentence the phone line now says = +0; a
  // number = the number, copy, edit, the sheet mask and the dial link = +4 over that.
  it('costs nothing on a case without a number, and at most four elements with one', async () => {
    const { container: a, unmount } = await open(detail(NO_NUMBER))
    const without = visible(a)
    unmount()
    const { container: b } = await open(detail(A_NUMBER))
    const withNumber = visible(b)
    expect(withNumber - without).toBeLessThanOrEqual(4)
  })
})
```

```jsx
// frontend/src/components/CaseContactDrawer.phone.test.jsx
// Feedback Round 1 / WP9: the Save-contact dialog shows the same phone control as the
// case header, and a number saved here dials at once. ADDED tests; the drawer's own
// test file is untouched.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { PrefsProvider } from '../prefs.jsx'
import { api } from '../api.js'
import { CaseContactDrawer } from './CaseContactDrawer.jsx'
import { setOfficer } from './role.jsx'

vi.mock('../api.js', () => ({
  api: {
    dictionary: vi.fn(), logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(),
    caseDetail: vi.fn(), uploadAttachment: vi.fn(), addContactNote: vi.fn(), addCaseNote: vi.fn(),
    downloadAttachment: vi.fn(), setCustomerPhone: vi.fn(),
  },
}))

const OVERRIDE = { phone_e164: '+66812345678', display: '081-234-5678', kind: 'MOBILE', set_by: 'thip',
                   set_at: '2026-10-23T09:15:00+07:00', reason: 'ลูกค้าให้เบอร์ใหม่', durable: true }
const ITEM = {
  customer: { uid: 'cu-1', customer_no: 'C-000912', display_name: 'อารีย์ พงษ์ไพบูลย์', phone_masked: 'xxx-xxx-xxxx',
              phone_on_sheet: false, phone_on_file: false, phone_e164: null, phone_override: null, line_id: null, officer: 'noon' },
  entity: 'SPV', aggregate_overdue: '6985.42', aggregate_outstanding: '211475.00',
  oldest_dpd: 22, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL', contact_lock: { state: 'OPEN' },
  case: { payment_status: 'LATE', dc_status: 'NO_ACTION', next_action: 'CALL', next_action_on: '2026-10-23', open_ptp: null },
}

beforeEach(() => {
  vi.clearAllMocks()
  setOfficer('thip')
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  api.caseDetail.mockResolvedValue({ payment_summary: null, work_item: { payment_position: null }, contact_log: [], events: [] })
  Object.defineProperty(window.navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true })
})

describe('the Save-contact dialog — the phone', () => {
  it('shows the entered number with copy and edit, and dials it', async () => {
    const item = { ...ITEM, customer: { ...ITEM.customer, phone_e164: '+66812345678', phone_on_file: true, phone_override: OVERRIDE } }
    renderIn('th', <MemoryRouter><CaseContactDrawer item={item} officer="noon" /></MemoryRouter>)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByTestId('cd-phone-number')).toHaveTextContent('081-234-5678')
    expect(within(dialog).getByTestId('cd-phone-copy')).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: 'โทร' })).toHaveAttribute('href', 'tel:+66812345678')
  })

  it('saves a number from the dialog, signed by the top-bar identity, and dials it at once', async () => {
    const onPhoneSaved = vi.fn()
    api.setCustomerPhone.mockResolvedValue({ customer: { uid: 'cu-1', phone_masked: 'xxx-xxx-xxxx', phone_on_sheet: false,
      phone_on_file: true, phone_e164: '+66812345678', phone_override: OVERRIDE } })
    renderIn('th', <MemoryRouter><CaseContactDrawer item={ITEM} officer="noon" onPhoneSaved={onPhoneSaved} /></MemoryRouter>)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('link', { name: 'โทร' })).toBeNull()
    fireEvent.click(within(dialog).getByTestId('cd-phone-edit'))
    const form = within(dialog).getByTestId('cd-phone-form')
    fireEvent.change(within(form).getByLabelText('เบอร์โทร'), { target: { value: '0812345678' } })
    fireEvent.change(within(form).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'ลูกค้าบอกระหว่างคุย' } })
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกเบอร์' }))
    await waitFor(() => expect(api.setCustomerPhone).toHaveBeenCalledWith('cu-1',
      { phone: '0812345678', reason: 'ลูกค้าบอกระหว่างคุย', by: 'thip' }))
    expect(await within(dialog).findByTestId('cd-phone-number')).toHaveTextContent('081-234-5678')
    expect(within(dialog).getByRole('link', { name: 'โทร' })).toHaveAttribute('href', 'tel:+66812345678')
    expect(onPhoneSaved).toHaveBeenCalledTimes(1)
  })

  it('never carries customer A\'s saved number over to customer B', async () => {
    api.setCustomerPhone.mockResolvedValue({ customer: { uid: 'cu-1', phone_on_file: true, phone_e164: '+66812345678', phone_override: OVERRIDE } })
    const { rerender } = renderIn('th', <MemoryRouter><CaseContactDrawer item={ITEM} officer="noon" /></MemoryRouter>)
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByTestId('cd-phone-edit'))
    fireEvent.change(within(dialog).getByLabelText('เบอร์โทร'), { target: { value: '0812345678' } })
    fireEvent.change(within(dialog).getByLabelText('เหตุผลที่แก้ไขเบอร์'), { target: { value: 'x' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'บันทึกเบอร์' }))
    await within(dialog).findByTestId('cd-phone-number')
    const other = { ...ITEM, customer: { ...ITEM.customer, uid: 'cu-2', display_name: 'ลูกค้า บี' } }
    rerender(<PrefsProvider><MemoryRouter><CaseContactDrawer item={other} officer="noon" /></MemoryRouter></PrefsProvider>)
    await waitFor(() => expect(screen.queryByTestId('cd-phone-number')).toBeNull())
    expect(screen.queryByRole('link', { name: 'โทร' })).toBeNull()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/screens/CustomerCase.phone.test.jsx src/components/CaseContactDrawer.phone.test.jsx`
Expected: FAIL. `case-phone-number` and `cd-phone-number` are not found, the header still carries `contact-disabled-why` with no number, and `api.setCustomerPhone` is never called.

- [ ] **Step 3: Measure BEFORE (after B5)**

Refresh `$SCRATCH/fe/src` from the worktree, then re-run B5 Step 4's command.
Expected: `PRE header=false phone=asFixture visible=109`, `WORKED … =128`, `PRE header=false phone=override visible=110`, `PRE header=true phone=asFixture visible=117`, `PRE header=true phone=override visible=118`, `WORKED header=true phone=override visible=137`.
Run `cd frontend && npx vitest run src/today-density.test.jsx 2>&1 | grep "^TODAY"`
Expected: `chrome=112 perRow=31 at 50 rows=1662`. **Paste both.**

- [ ] **Step 4: Implement — the case header**

`CustomerCase.jsx`:

(a) After line 26: `import { PhoneOnCase } from '../components/PhoneOnCase.jsx'`.

(b) After B5's `calcHas` block, add:

```jsx
  // Feedback Round 1 / WP9 (F9 (a)): a phone number a person enters, signed by the
  // top-bar identity. A refusal throws back into PhoneOnCase, which prints it beside
  // its own form; success re-reads the case so every served key is the server's.
  async function savePhone(payload) {
    const res = await api.setCustomerPhone(customerUid, { ...payload, by })
    setFlash(t('case.phone.saved'))
    await load()
    return res
  }
```

(c) Keep the R5-F01 comment block at lines 522–535, and add one line at its end before `*/}`:

```
                WP9: PhoneOnCase keeps this guard (phone_on_file === false → absence) and adds
                the entered number, copy and edit; both objects now serve the same keys.
```

Replace lines 536–538 with:

```jsx
            <PhoneOnCase customer={{ ...customer, ...(item?.customer || {}) }} onSave={savePhone} prefix="case" />
```

(d) Lines 576–577: `ContactActions` gains `why`:

```jsx
            {/* WP9: with no number the phone line above already says so, beside the
                add control — J3-14's reason is on the screen once, not twice. With a
                number and no LINE id, ContactActions still says why LINE is off. */}
            <ContactActions item={item} onLog={() => setDrawer(true)} openCase={false}
                            why={Boolean(item?.customer?.phone_e164)}
                            logLabel={contactLocked ? t('cdrawer.alt.SECOND_CONTACT_NOT_COUNTED') : undefined} />
```

(e) In the `CaseContactDrawer` mount (1855–1874), after the `onCaseNote={…}` prop, add:

```jsx
          // WP9: a number saved in the dialog re-reads the case, so the header
          // behind it shows the same number the dialog now does.
          onPhoneSaved={() => { load() }}
```

- [ ] **Step 5: Implement — the dialog**

`CaseContactDrawer.jsx`:

(a) After line 16: `import { PhoneOnCase } from './PhoneOnCase.jsx'`.

(b) Lines 254–255, the signature, becomes:

```jsx
export function CaseContactDrawer({ item, officer, businessDate, nextName, onClose, onLogged, onNext, onRenegotiate, sopStep,
                                    paymentSummary = undefined, paymentPosition = undefined, timeline = null, onCaseNote = undefined,
                                    onPhoneSaved = undefined }) {
```

(c) After line 327 (`const [extraRows, setExtraRows] = useState([])`):

```jsx
  // WP9 (design F9 (a)): the phone fields the server answered with after a save in
  // THIS dialog, laid over the item the caller handed in, so the number and the
  // dial button change at once. Customer-scoped: cleared on identity change below.
  const [phoneServed, setPhoneServed] = useState(null)
```

(d) In the identity-reset effect, after line 432 (`setExtraRows([])`): `    setPhoneServed(null)`.

(e) After line 462 (`const by = acting || officer`):

```jsx
  const shownCustomer = phoneServed ? { ...customer, ...phoneServed } : customer
  const dialItem = phoneServed ? { ...item, customer: shownCustomer } : item
  async function savePhone(payload) {
    const res = await api.setCustomerPhone(customer.uid, { ...payload, by })
    setPhoneServed(res?.customer || null)
    if (typeof onPhoneSaved === 'function') onPhoneSaved(res)
    return res
  }
```

(f) Lines 900–903, the phone guard, become:

```jsx
              {/* WP9: the same phone control as the case header (R5-F01's guard lives inside it). */}
              <PhoneOnCase customer={shownCustomer} onSave={savePhone} prefix="cd" />
```

(g) Line 909: `<ContactActions item={dialItem} log={false} openCase={false} size="btn--sm" />`.

- [ ] **Step 6: Run the focused tests and every pin that reads these two screens**

Run: `cd frontend && npx vitest run src/screens/CustomerCase.phone.test.jsx src/components/CaseContactDrawer.phone.test.jsx src/screens/CustomerCase.test.jsx src/screens/CustomerCase.header.test.jsx src/screens/CustomerCase.paymentStatus.test.jsx src/components/CaseContactDrawer.test.jsx src/components/DrawerHistory.test.jsx src/screens/Today.test.jsx src/screens/Today.board.test.jsx src/round4.test.jsx src/density.test.jsx src/today-density.test.jsx`
Expected: PASS (7 + 3 new; the rest unchanged: CustomerCase 46, drawer 47, Today 32, board 10, round4 45).

Run: `cd frontend && npx vitest run && npx vite build`
Expected: PASS at the Task-start baseline + 10. **Paste the count.**

- [ ] **Step 7: Measure AFTER**

Run: `cd frontend && npx vitest run src/density.test.jsx src/today-density.test.jsx 2>&1 | grep -E "^PRE-CONTACT|^WORKED|^TODAY"`
Expected: `PRE-CONTACT+PAY … visible=109`, `WORKED+PAY … visible=128`, `TODAY chrome=112 perRow=31 at 50 rows=1662`.

Refresh `$SCRATCH/fe/src`, re-run B5 Step 4's command.
Expected: `PRE header=false phone=asFixture visible=109`, `PRE header=false phone=override visible=113`, `PRE header=true phone=asFixture visible=117`, `PRE header=true phone=override visible=121`, `WORKED header=true phone=override visible=140`. **Paste both.**

If the fixture totals exceed 109/128, STOP and report: this plan spends no numbered edit, and the only lever measured is the `why` prop in Step 4(d).

Dialog (by hand, no census): in `$SCRATCH/fe`, render `<CaseContactDrawer item={…} />` with no number and with an override, and log `container.querySelector('.cd-head').querySelectorAll('*').length`.
Expected: 20 and 23 (HEAD: 19 and 20).

- [ ] **Step 8: The harness**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED. **Paste backend / frontend / e2e counts.**

- [ ] **Step 9: Commit**

```bash
cat > "$SCRATCH/b7b-commit.txt" <<'MSG'
feat(case, dialog): the phone on the case header and in the Save-contact dialog — copy, edit with a reason, and a dial button that dials it

Design WP9 / F9 (a). The case header and the dialog mount PhoneOnCase; a save in the
dialog updates its own dial button at once and re-reads the case page behind it. The
case header's no-phone sentence is said once, by the phone line. Density: fixtures
109/128 unchanged; the real served header with a number 121/140, equal to HEAD (B5's
give-back pays for it); Today untouched at 31/112/1,662.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
MSG
git add frontend/src/screens/CustomerCase.phone.test.jsx frontend/src/components/CaseContactDrawer.phone.test.jsx
git commit -F "$SCRATCH/b7b-commit.txt" -- frontend/src/screens/CustomerCase.jsx frontend/src/components/CaseContactDrawer.jsx frontend/src/screens/CustomerCase.phone.test.jsx frontend/src/components/CaseContactDrawer.phone.test.jsx
```

---

## Self-review (P2)

**Spec coverage, design §3 WP8, line by line.**
- "The header keeps **figures only**: name, ids, entity, officer, phone (WP9), last contact, arrears/outstanding, DPD and the ladder line, the two status chips, next action, and the actions."
  - Covered by B5 (Step 6 c/d) and pinned by `CustomerCase.header.test.jsx` "draws no explanation toggle in the header".
  - The status chips and next action are cards below the header today. B5 moves nothing into or out of them.
- "Everything that explains a figure — 'Details', 'Allocation pending OD-02', 'How this figure is worked out', the penalty formula — moves to a 'รายละเอียดการคำนวณ' fold beside the history fold … closed by default."
  - B5 Step 6e moves `arrears-hold-toggle` ("รายละเอียด" → "ทำไมยอดค้างยังไม่เปลี่ยน"), `arrears-hold-detail-field` (`case.allocationPending`), `mp-note-toggle` ("ยอดนี้คิดอย่างไร") and `mp-formula-detail-field`.
  - The ladder's "ทำไม" is also an explanation of a figure, so it moves too.
  - Tests: "puts every explanation in one closed fold, placed right after the history fold" and "still opens each explanation".
- "(a) settings (penalty rate, grace days) get a 'แก้ไขที่ตั้งค่า' link visible to the Owner, opening the WP10 form at that field."
  - B5 builds `calc-settings-*` with `/settings?field=<key>`. The Owner-only test and the others-see-none test cover it.
  - Opening at the field is P3/B9's half (see Depends on).
- "(b) per-case values editable in place — payment status, follow-up status, next action already; the phone in WP9." Nothing to build beyond WP9.
- "`MoneyPosition`'s explanations render into that fold via a slot" (brief) is the `slot` prop, 'face' | 'fold'. It is two instances rather than a portal (no refs, no double render), and `noteDisclosure` is exported so the page never restates the rule.

**Spec coverage, design §3 WP9.**
- "`records.customer_contact` (`customer_uid, phone_e164, set_by, set_at, reason, active`)": B6 Step 4, plus `uid` and `kind` and one active row per customer.
- "copy button": B7a `phone-copy`, which copies the display form.
- "edit control (reason required, E.164 normalised, Thai mobile/landline shapes validated)": B7a form, B6 `normalise` (8 accepted and 8 refused shapes tested), and `reason_required`.
- "the dialog shows the same": B7b Step 5, the same component with prefix `cd`.
- "Today's dial buttons use it when present (`phone_on_file` becomes true)": B6 serves `phone_e164` and `phone_on_file` first on `/v1/today`. Today.jsx already dials a served `phone_e164`, pinned by `Today.test.jsx:238-243`, so it needs 0 edits. The dialog's dial button updates at once (B7b drawer test).
- "The sheet's masked number stays visible beside it as 'ชีตระบุ 08x-xxx-4810'": B7a `phone-sheet`. `phone_masked` is never touched (`test_journey_rebuild.py:63`).
- Brief: "`POST /v1/cases/by-customer/{uid}/phone` reason required, audit `PHONE_SET` with no number in the detail". B6 route plus `test_the_audit_row_says_set_and_never_carries_the_number`, which also cuts a number typed into the reason.

**Placeholder scan.** No "TBD", "add validation" or "similar to Task N". Each task repeats the code it needs. Two instructions are copy-in-place edits, each anchored on quoted current text: keep the R5-F01 comment and add a line; keep the two MoneyPosition comment blocks above line 631.

**Name consistency with what this section consumes.**
- `who(body, x_volt_officer)` (`routers/today.py:27`), `_case_or_404` (`:635`), `problem_from` (`:44`, `pointer` → `errors[0]`).
- `CaseError(code, detail, message_th, **extra)` (`cases.py:53`), `audit.describe(act, subject, detail)` (`audit.py:136`), `audit_store.read({}, limit=1, before_seq=None)` (as `test_payment_status_adjust.py:138`).
- `db.configured` and `db.connect` (`db.py`), `migrate.apply` (`migrate.py:83`), `journey.customer_by_uid` (`journey.py:176`).
- `ContactActions({ why })` (`CaseContactDrawer.jsx:186`), `RowExpandToggle({ label })` (`RowPattern.jsx:104`), `refusalText` (`problem.js`), `useOfficer` (`role.jsx`).
- B7a produces `api.setCustomerPhone`; B7b consumes it with the same name.
- B6 produces `phone_override.display`, `phone_on_sheet` and `durable`/`note_th`; B7a reads exactly these.

**Assumptions not verifiable in the code.**
1. P3's B9 honours `/settings?field=<key>`. Until it does, the link opens Settings at the top.
2. F9 (a) "any officer" is read as all five API roles, OPS included, the same as `/dc-status` and `/payment-status`.
3. The Thai numbering shapes (mobile 06/08/09 + 8 digits; landline 02–07, 9 digits) and the refusal of 01x and short codes were not checked against NBTC's current numbering plan.
4. The per-request ContextVar memo was verified by probe on FastAPI 0.128.8 / Starlette 0.49.3 (this venv). Staging runs FastAPI 0.141 (memory note), where it is unverified. If context propagation into the threadpool changed, `active_for` still works, but it reads the table per row.
5. `navigator.clipboard` needs a secure context. Staging is https; over plain http the copy button hides, and the number stays select-all.
6. The number is copied in the displayed form (`081-234-5678`), not E.164. That is a UX choice not stated in the design.
7. Runtime grants for schema `records` (note 10 §9.4, another session's uncommitted `migrate.py`) must cover `records.customer_contact` on staging.
8. The planning probe ran B6's DB test against `volt_feedback_r1`. That left an EMPTY `records.customer_contact`, with exactly this plan's DDL, in that database. Dropping it was refused by the permission classifier. Implementers use `<task-db>`; if one is `volt_feedback_r1`, `CREATE TABLE IF NOT EXISTS` is a no-op on an identical table.
9. Error ids DEBT-COL-0463/0464 are claimed here. P5 must start at 0465 if it adds CaseError rows to `problem_from`.


<!-- ===== cluster section: P3-wp10-wp11.md ===== -->

# Round B — cluster P3: WP10 (Settings redesign + Users tab) and WP11 (Greeting)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

Planner P3, 2026-09-15. Written against `feedback-r1` at **b5bdc7c** and re-checked at **81d2760**. The brief named caddc4b; four commits by another session landed while this was planned (c7d2552, b5bdc7c, 91b8519, 81d2760). None of the four touches a file below except `frontend/src/i18n-admin.js` (+5 `peak.*` lines at 598/1126), and every anchor used here is unchanged. The worktree also carried another agent's uncommitted edit to `backend/app/attachments/guard.py` + its test while this was measured — not a file of this cluster.

**Every code block below was built and run** in a scratch copy of the tree (`scratchpad/rounds-bc/P3/be`, `P3/fe`, scratch database `volt_p3_scratch`, dropped after). The counts quoted as "measured" come from those runs, not from reasoning.

**Goal:** a Manager tunes settings in a grouped form that says who changed each value last; the Owner and Managers manage who may sign in with Google (invite, disable) on a ผู้ใช้ tab without redeploying the env secret; every signed-in person names themself; Today greets them by that name.

**Architecture:** B8 keeps a per-key change stamp in a second per-session `Store` beside the settings it describes. B10 adds one durable table `records.user_account`, merged over the env `AUTH_ALLOWLIST` seed at every Google sign-in and on every authenticated request (through a hook on the existing login middleware), with a 30-second read cache. B12 serves `display_name` (+ its source and fallback) on `/v1/auth/me`. The screens only render what the server serves.

## Tasks, and the order they run in

| Id | What | Runs after |
|---|---|---|
| **B8** | `changed_by` / `changed_by_role` / `changed_at` per config key | — |
| **B9** | Settings: config rows → grouped forms (ids kept), `/settings#cfg-<key>` anchor | B8 |
| **B10a** | `records.user_account` + `app/user_accounts.py` (the store, merge rule, refusals) | — |
| **B10b** | The routes: `GET/POST /v1/auth/users`, `POST /v1/auth/users/{uid}:disable`; sign-in merge; the middleware ends withdrawn sessions | B10a |
| **B12a** | `display_name` on `/v1/auth/me` and the sign-in answer; `PUT /v1/auth/me/profile` | B10b |
| **B11** | The ผู้ใช้ tab on Settings; the display-name field in the identity menu | B9, B12a |
| **B12b** | Today's title `สวัสดี {name}` + one rotating positive line | B12a, **P1's B4** |

Note 11's B10 is split into B10a (store) and B10b (HTTP + middleware), and B12 into B12a (backend) and B12b (screen). Each part is independently testable.

## Shared files (other clusters touch these too)

| File | This cluster's exact region | Other clusters |
|---|---|---|
| `backend/app/schema.sql` | **B10a appends** one table + two indexes after the last line (274, `attachment_target_idx`) | P2 B6 (`records.customer_contact`), P5 C2 (`records.notice`) — all append; take theirs, then append |
| `backend/app/main.py` | B10b: `_lifespan` body `:55-67`; the login block `:257-265` | P5 C2/C3 add `include_router(calendar_router)` near `:1570-1599` — disjoint lines |
| `frontend/src/screens/Today.jsx` | **B12b only:** import line `:5`; one exported helper inserted before `export default function Today()` `:135`; two lines after `const roster = useRoster()` `:172`; **the `<h1 className="page-title">` line `:751`**; branch B also inserts one line right after `<p className="page-sub" aria-live="polite">` `:754` | P1 B1–B3 (reminders block, FilterBar, notices fold — the header's tier strip and folds), P2 (dial buttons on rows) |
| `frontend/src/i18n-today.js` | B12b: 6 keys after `'today.title'` at `:151` (EN) and `:740` (TH) | P1, P2 |
| `frontend/src/i18n-admin.js` | B9: 41 keys, B11: 23 keys — all inserted right after `'set.title'` at `:237` (EN) and `:802` (TH) | P4 (weekly), P5 C1 (`peak.*`) |
| `frontend/src/i18n-journey.js` | B11: 4 keys after `'auth.retry'` at `:418` (EN) and `:852` (TH) | P5 C3 (calendar) |
| `frontend/src/api.js` | B11: 4 bindings after `authLogout` `:353` | P1 (reminders), P2 (phone), P5 (calendar) |
| `frontend/src/admin.css` | B9, B11: append at end (423 lines) | P4 |
| `frontend/src/today.css` | B12b branch A: append at end (949 lines) | P1 |
| `frontend/src/app.css` | B11: 3 rules after `.pop__panel .role-switch__ask` `:459` | none known |

Files only this cluster touches: `backend/app/config.py`, `backend/app/routers/settings.py`, `backend/app/auth.py`, `backend/app/routers/login.py`, `backend/app/user_accounts.py` (new), `frontend/src/screens/Settings.jsx`, `frontend/src/components/UsersPanel.jsx` (new), `frontend/src/components/RoleSwitcher.jsx`.

## Depends on (other clusters)

- **B12b ← P1 B4.** Today's chrome is AT its cap (112, measured). B12b's positive line costs +1 when it is its own `<p>` (measured 113). B12b reads B4's pasted census and takes branch A (own `<p>`) if chrome ≤ 111, branch B (a text node in the sub-line, measured +0) if it is 112. If P1 has not landed when B12b is dispatched, B12b takes branch B.
- **P2 B5 → B9 (consumes, not blocks).** B5's "แก้ไขที่ตั้งค่า" link targets `/settings#cfg-<key>`. B9 gives every field `id="cfg-<key>"` and scrolls a `#cfg-` hash into view once the rows load.

## Global constraints (every task carries these)

- **Baseline to beat (at caddc4b):** backend 1,022 passed / 11 skipped, frontend 726 passed / 63 files, e2e 31 of 31 (`scripts/verify_all.sh`). At b5bdc7c the backend collects 1,043 items (measured with `--collect-only`); the controller pastes the live baseline.
- **Test contract:** a pinned (pre-existing) test changes only as a numbered edit 36–39, measured first, carrying `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`. Adding tests is free. **This cluster spends none** (measured below).
- **Density ratchets:** `density.test.jsx` caps the case page at 109 / 128 (untouched here). `today-density.test.jsx` caps Today at 31 per row, 112 chrome, 1,662 per 50-row page; the controller's ruling keeps those caps. Every screen task measures before and after and pastes the census lines.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns.
- REQ-COL-075: `payment_status` keeps its five values; two fields; `StatusPair` unmodified (not touched here).
- PKD-001: `integrations/peak.py` untouched.
- Raw-body uploads only (no `UploadFile`) — no upload here.
- Honesty: a configured-but-unreachable dependency refuses (`user_list_unreachable` 503); an unconfigured one is labelled (`durable: false` + `note_th`); every refusal is RFC 9457 with `message_th`; an unknown body key is refused, not ignored.
- PDPA: e-mail addresses appear only in `records.user_account` and the audit **subject**. No refusal detail, message, audit detail or URL carries one. `AUTH_MODE` is never written into `backend/.env`; login is switched on in tests with `auth.set_config(auth.load_config(environ_dict, env_file=tmp_path / "none"))`. Test-account passwords (`~/.volt-test-accounts.json`) are never printed — tests use their own `FAST`-round hashes.
- Every write route is role-gated where the design names a role, and audited with `audit.describe(act=…, subject=…, detail=…)` **before** the side effect. Sign with `who(body, x_volt_officer)` from `routers/today.py`; `officers.sign` returns a tuple.
- Strings in `i18n-*.js` (flat `*_EN` / `*_TH` objects). **Every new key was grepped across all four tables and `prefs.jsx` first** (command in each task; measured: 0 hits for `set.key.`, `set.unit.`, `set.group.`, `set.source.`, `set.changed`, `set.lockedFor`, `set.tab`, `set.users.`, `auth.profile.`, `today.hello`).
- Python 3.9-safe. CSS: real tokens only (`--ink-*`, `--line-default`, `--caption-12`, `--label-13`, `--body-14`, `--body-strong-14`, `--font-mono`, `--status-current`), literal px spacing, no hex.
- Frontend patterns: async effects carry an `alive` guard; a `vi.mock('../api.js')` object returns a Promise from every binding called at mount; role in tests via `window.localStorage.setItem('volt.role', …)`.

**Worktree rules (repeated in each task as "W").** Backend interpreter `backend/.venv/bin/python`; run pytest without `-q`. Each backend run names `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data`. Never set `DATABASE_URL` to `volt_local`. Never a bare `git stash`. Never `cd` into `/Users/parattakorn/volt-debt-prototype`. Commit with a message file plus a pathspec (`git commit -F <file> -- <paths>`), message ending with the two lines `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W`. Never `git add -A`. Check `git log --oneline -3` before the baseline run: other sessions commit to this branch.

## Rulings made in this cluster (each with its cost)

1. **B8 — "persisted with the config store" means the per-session `Store`.** `/v1/config` values are not in Postgres tables: `config.py:282` keeps a `Settings` per tester session in `session.Store`, pickled into `app.session_state` when a database is configured (discarded on a deploy by `K_REVISION`), memory otherwise. The stamps go in a second Store `config.changed` with exactly that lifetime. `schema.sql` is not touched by B8. *Cost:* the last-changed line is per session, like the value it describes; the org-wide trail stays the audit log (B8 adds `CONFIG_SET` rows to it).
2. **B8 — `PUT /v1/config` checks every key before writing any.** Today a body whose second key is refused leaves the first key changed. *Cost:* a multi-key body with one bad key now writes nothing. Measured: no pinned test sends such a body (151 config/auth tests pass).
3. **B10 — with login off, all four user routes answer `auth_off` (404).** The list governs Google sign-in, which only exists with login on, and an invitation made while any browser may claim OWNER by header would outlive that mode. *Cost:* the local prototype (login off) shows the ผู้ใช้ tab as one sentence, with no form.
4. **B10 — the middleware opens exact paths, not the `/v1/auth/` prefix.** `auth.py:352` lets every `/v1/auth/*` path through without a session; the new user routes live under that prefix and must not. `OPEN_PATHS` names the five that stay open. *Cost:* none measured (test_auth_http 25/25).
5. **B10 — a switching session (a test account with role `ANY`) cannot manage users** (`identity_not_fixed`, 403). It can claim OWNER by header, so it cannot vouch for an invitation. *Cost:* the shared `tester` login cannot invite; `owner.test` / `manager.test` can.
6. **B10 — rank:** OWNER 4 > MANAGER 3 > SUPERVISOR 2 > OFFICER 1 = OPS 1. An equal role may be granted. Disable is refused on a role above the actor's and on oneself. A disabled row comes back only by being invited again; nothing deletes a row or a seed entry.
7. **B10 — ending a session.** The cookie is stateless, so the middleware asks `user_accounts.session_allowed` on every authenticated request, and `/v1/auth/me` (an open path) asks too. A Google session ends when its person is disabled, dropped from the seed, or re-invited with a different role or officer. The answer comes from a cache refreshed at most every **30 s**, and at once on the instance that made the change. *Cost:* on another Cloud Run instance a disabled session keeps working for up to 30 s; one synchronous Postgres read every 30 s per instance inside the ASGI middleware. The refusal reuses code `auth_required` (with `extensions.reason = "account_withdrawn"`), because `api.js signalAuth` brings the login screen back on exactly that code — no frontend change needed.
8. **B10 — a seed entry's list uid is `env-<sha256(email)[:16]>`**, so the disable URL never carries an e-mail into a request log. DB rows use their numeric id.
9. **B10 — `invited_by` / `disabled_by` hold the officer uid** from `who(body, x_volt_officer)` (the middleware rewrote both from the session). The audit row's `actor_claimed` keeps the session subject, as today.
10. **B12a — `/v1/auth/me` serves `display_name`, `display_name_source` (`PROFILE` | `EMAIL` | `USERNAME`) and `display_name_fallback`.** The identity menu names the fallback without deriving it from the subject.
11. **B12b — the positive line rotates by served business day** (`floor(epoch days) % 5 + 1`), not `Math.random`, so tests are stable and the line changes daily. It never contains a digit (tested for both languages).
12. **B9 — `review_sla_hours` is filed under "การเตือนและกำหนดเวลาตอบ".** The design's eight headings name no group for it. An unfiled key renders under "ค่าอื่น ๆ" so a new key never vanishes.
13. **B11 — the identity-menu keys go in `i18n-journey.js`** (`auth.profile.*`, beside `auth.*`), not `i18n-admin.js` as note 11's header says. The ผู้ใช้ tab's keys are `set.users.*` in `i18n-admin.js`.

## Measured before planning (at b5bdc7c; frontend at the caddc4b copy, unchanged files)

```
TODAY  chrome=112  perRow=31  at 50 rows=1662  (1=143, 11=453, 21=763; slope2=31)
TODAY  full page (50 rows) visible=1662
```

With B12b branch A (own `<p>`) in a scratch copy:
```
TODAY  chrome=113  perRow=31  at 50 rows=1663  (1=144, 11=454, 21=764; slope2=31)   ← 2 tests fail
```
With branch B (text node in the sub-line):
```
TODAY  chrome=112  perRow=31  at 50 rows=1662  (1=143, 11=453, 21=763; slope2=31)   ← 5/5 pass
```

Full suites in the scratch copy with every task below applied (copy base: the tree at planning time, 41 backend and 25 frontend tests added by this cluster):
- backend **1,068 passed / 11 skipped**;
- frontend **751 passed / 67 files** with B12b branch B; with branch A, 748 passed and the two density tests fail, as measured above.

Pins, measured:
- `frontend/src/screens/Settings.test.jsx` — 16 tests. 9 of them pin config ids: `cfg-<key>` at 74, 82, 94, 103, 108, 119, 129, 137, 171, 173, 209, 227; `cfg-edit-` at 97, 103, 109, 123, 130, 138, 211, 229; `cfg-input-` at 110, 139, 212; `cfg-save-` at 111, 140, 217, 230; `cfg-problem-` at 142, 231; `cfg-open-` at 122, 172, 173; `cfg-decided-` at 96, 121; `cfg-owner-only-` at 100; `state-locked` 75; `state-decided` 101; `.pending-badge` 83; `band-set-code-why` 215; `queryByRole('button')` inside a row at 76 and 88. **16/16 pass after B9 and after B11: 0 edits.** `data-testid="config-table"` is removed; grep finds no test or script using it.
- Today's title: **0 pins.** No test or script matches `today.title`, a heading named "Today"/"วันนี้", or `page-title` text. `today-density.test.jsx:94` and `density.test.jsx:334` wait for `findByRole('heading', { level: 1 })` only. Measured: Today.test.jsx 32/32, Today.board.test.jsx 10/10, round4.test.jsx 45/45 pass with the greeting.
- `frontend/src/components/IdentityMenu.session.test.jsx` — 3 tests, 3/3 pass with the name field: 0.
- Backend: `test_auth_core.py` (19) pins `load_config(...).allowlist` equality at :51-55 and `me_payload` keys at :159-166 — both functions are unchanged. `test_auth_http.py` (25) pins `/v1/auth/config` JSON and `/me` → `auth_off` at :38-43, open `/v1/auth/config` at :45-52, Google sign-in at :230-263, `PUT /v1/config` under login at :279-291. `test_audit_coverage.py` (4). Config tests `test_round1_p3.py:308-376`, `test_round2.py:436-442`, `test_today_and_pipeline.py:177-179`, `test_board_derived.py:254-260`. **All pass unchanged: 0 edits.** `tests/conftest.py` is not touched: the new test files reset `user_accounts` in their own fixtures.

---

### Task B8: `changed_by` / `changed_at` per config key

**Files:**
- Modify: `backend/app/config.py:282-290` (the `_store` block, `for_current`, `reset`)
- Modify: `backend/app/routers/settings.py:1-8` (imports), `:90-118` (`_config_rows`), `:121-166` (`put_config`)
- Create: `backend/tests/test_settings_changed_by.py`

**Interfaces:**
- Consumes: `routers.today.who(body, header, role=...)` (today.py:27) → a string; `clock.stamp()` → `"2026-10-23T09:00:04"`; `audit.describe`.
- Produces:
  - `config.changed_for_current() -> dict`, shaped `{key: {"by": str, "role": "MANAGER"|"OWNER", "at": str}}`. `config.reset()` also clears it.
  - Every row of `GET /v1/config` and of the `PUT /v1/config` answer gains `changed_by` (str|null), `changed_by_role` (str|null) and `changed_at` (business-clock ISO seconds or null). B9 consumes them.
  - `PUT /v1/config` gains the header `X-Volt-Officer` (optional). An unchanged value is not stamped.
  - Audit: act `CONFIG_SET`, subject `("config", "<key>[,<key>…]")`, detail `{"keys": {key: {"from": str, "to": str}}}`.

**Pins:** 0. The config tests above keep passing (measured 151 passed across `test_settings_changed_by.py`, `test_round1_p3.py`, `test_round2.py`, `test_today_and_pipeline.py`, `test_board_derived.py`, `test_auth_http.py`). Density: not a screen.

- [ ] **Step 1 (W):** `git log --oneline -3`; note the head. Every command below runs from the worktree root.

- [ ] **Step 2: Write the failing test** — create `backend/tests/test_settings_changed_by.py`:

```python
"""B8 (Feedback Round 1 / WP10): every config row says who changed it last, and when.

Each test uses its own TestClient, so its own volt_session cookie and its own
per-session Settings and change stamps — nothing here leaks into another test's
session, and no test has to put a value back.
"""
from fastapi.testclient import TestClient

from app import audit_store
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}


def _rows(client, headers=MANAGER):
    return client.get("/v1/config", headers=headers).json()["config"]


def test_a_key_nobody_changed_says_so_with_nulls():
    row = _rows(TestClient(app))["pipeline_lookahead_days"]
    assert (row["changed_by"], row["changed_by_role"], row["changed_at"]) == (None, None, None)


def test_a_save_stamps_the_signer_the_role_and_the_business_clock():
    client = TestClient(app)
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 5}, headers=MANAGER)
    assert r.status_code == 200, r.json()
    row = r.json()["config"]["pipeline_lookahead_days"]
    assert row["value"] == "5"
    assert row["changed_by"] == "settasak" and row["changed_by_role"] == "MANAGER"
    assert row["changed_at"].startswith("2026-10-23T")
    assert _rows(client)["pipeline_lookahead_days"]["changed_by"] == "settasak"
    assert _rows(client)["review_sla_hours"]["changed_by"] is None


def test_an_officer_identity_pressing_manager_is_signed_by_the_role_default():
    """officers.sign (S2-04): an identity the registry knows as an OFFICER cannot sign a
    Manager act, so the stamp names the role's default identity, never nantapol."""
    client = TestClient(app)
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 4},
                   headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "nantapol"})
    assert r.json()["config"]["pipeline_lookahead_days"]["changed_by"] == "settasak"


def test_saving_the_value_it_already_holds_is_not_a_change():
    client = TestClient(app)
    current = _rows(client)["review_sla_hours"]["value"]
    r = client.put("/v1/config", json={"review_sla_hours": current}, headers=MANAGER)
    assert r.status_code == 200 and r.json()["config"]["review_sla_hours"]["changed_by"] is None


def test_a_refused_key_writes_nothing_not_even_the_valid_key_before_it():
    client = TestClient(app)
    before = _rows(client)["pipeline_lookahead_days"]["value"]
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 9, "reminder_offsets_days": "x"}, headers=MANAGER)
    assert r.status_code == 422
    row = _rows(client)["pipeline_lookahead_days"]
    assert row["value"] == before and row["changed_by"] is None


def test_the_stamp_is_per_session_like_the_value():
    first, second = TestClient(app), TestClient(app)
    first.put("/v1/config", json={"pipeline_lookahead_days": 6}, headers=OWNER)
    assert _rows(first)["pipeline_lookahead_days"]["changed_by"] == "owner"
    assert _rows(second)["pipeline_lookahead_days"]["changed_by"] is None


def test_the_change_is_audited_with_its_keys_and_values():
    client = TestClient(app)
    client.put("/v1/config", json={"pipeline_lookahead_days": 7}, headers=MANAGER)
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "CONFIG_SET" and entry["subject_type"] == "config"
    assert entry["subject_uid"] == "pipeline_lookahead_days"
    assert entry["detail"]["keys"]["pipeline_lookahead_days"]["to"] == "7"
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data .venv/bin/python -m pytest tests/test_settings_changed_by.py`
Expected: **7 failed.** Five fail with `KeyError: 'changed_by'`. `test_a_refused_key_writes_nothing_not_even_the_valid_key_before_it` fails on the value: today the first key IS written before the second is refused. `test_the_change_is_audited_with_its_keys_and_values` fails because `entry["act"]` is `None`.

- [ ] **Step 4: The second Store** — in `backend/app/config.py` replace

```python
_store = Store(Settings, key="config.settings")


def for_current() -> Settings:
    return _store.for_current()


def reset():
    _store.reset()
```

with

```python
_store = Store(Settings, key="config.settings")

# Feedback Round 1 / WP10 (B8): who last changed each key and when — {key: {"by",
# "role", "at"}} — kept in the same per-session Store family as the values it
# describes, so it persists exactly as they do (app.session_state when a database is
# configured, memory when not) and a deploy discards both together. A second Store,
# not a Settings field: a Settings pickle written before the field existed would
# restore without it (session_store_db keeps "dev" pickles across code changes).
_changed_store = Store(dict, key="config.changed")


def for_current() -> Settings:
    return _store.for_current()


def changed_for_current() -> dict:
    return _changed_store.for_current()


def reset():
    _store.reset()
    _changed_store.reset()
```

- [ ] **Step 5: Serve and stamp** — in `backend/app/routers/settings.py`:

(a) imports, lines 4-6, replace

```python
from .. import dictionaries, errors, journey
from ..config import DECIDED, PENDING, settings
from ..money import band_sets
```

with

```python
from .. import audit, clock, dictionaries, errors, journey
from ..config import DECIDED, PENDING, changed_for_current, settings
from ..money import band_sets
from .today import who
```

(`routers/attachments.py:26` already imports `who` the same way at module level.)

(b) in `_config_rows`, replace

```python
    keys = {}
    for key in EDITABLE + LOCKED + ("penalty_invoicing_enabled", "power_restriction_enabled"):
        value = getattr(settings, key, None)
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)       # N2-13: "3,0", not "(3, 0)"
        decided = DECIDED.get(key)
        keys[key] = {"value": str(value) if value is not None else None,
                     "state": "LOCKED" if key in LOCKED else (
                         "OPEN" if key in OPEN else ("DECIDED" if decided else "SET")),
                     "owner": OPEN.get(key),
                     # J-53: `editable` is answered for the CALLER's role; `editable_by` names the floor.
                     "editable": _may_edit(key, role), "editable_by": _editable_by(key)}
```

with

```python
    keys = {}
    stamps = changed_for_current()
    for key in EDITABLE + LOCKED + ("penalty_invoicing_enabled", "power_restriction_enabled"):
        value = _shown(getattr(settings, key, None))
        decided = DECIDED.get(key)
        stamp = stamps.get(key)
        keys[key] = {"value": value,
                     "state": "LOCKED" if key in LOCKED else (
                         "OPEN" if key in OPEN else ("DECIDED" if decided else "SET")),
                     "owner": OPEN.get(key),
                     # J-53: `editable` is answered for the CALLER's role; `editable_by` names the floor.
                     "editable": _may_edit(key, role), "editable_by": _editable_by(key),
                     # B8: who changed it last in this session's store, and when (None = never).
                     "changed_by": stamp["by"] if stamp else None,
                     "changed_by_role": stamp["role"] if stamp else None,
                     "changed_at": stamp["at"] if stamp else None}
```

(c) directly above `@router.put("/v1/config")`, add

```python
def _shown(value):
    """A config value as the rows serve it: None stays None; a tuple reads "3,0"."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)          # N2-13: "3,0", not "(3, 0)"
    return str(value)


```

(d) the signature — replace

```python
def put_config(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
```

with

```python
def put_config(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
               x_volt_officer: str = Header(default=None)):
```

(e) the loop head — replace `    for key, value in body.items():` (the one in `put_config`, line 127) with

```python
    staged = []
    for key, value in body.items():
```

(f) the loop's last statement and the return — replace

```python
        setattr(settings, key, new)
    return _config_rows(role)
```

with

```python
        staged.append((key, current, new))
    # B8: every key is checked before any is written, so a refused second key no longer
    # leaves the first one changed, and the stamp names only what really moved.
    moved = [(key, old, new) for key, old, new in staged if new != old]
    if moved:
        by = who({}, x_volt_officer, role=role)
        audit.describe(act="CONFIG_SET", subject=("config", ",".join(key for key, _o, _n in moved)),
                       detail={"keys": {key: {"from": _shown(old), "to": _shown(new)} for key, old, new in moved}})
        stamps = changed_for_current()
        at = clock.stamp()
        for key, _old, new in moved:
            setattr(settings, key, new)
            stamps[key] = {"by": by, "role": role, "at": at}
    return _config_rows(role)
```

`who({}, …)` gets an empty body on purpose: `PUT /v1/config` refuses every key it does not edit, so a `by` can never be in it.

- [ ] **Step 6: Run the focused tests, then the pinned config and auth tests**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_settings_changed_by.py tests/test_round1_p3.py tests/test_round2.py tests/test_today_and_pipeline.py tests/test_board_derived.py tests/test_auth_http.py`
Expected: **151 passed** (measured).

- [ ] **Step 7: Run the suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; backend = baseline + 7. Paste the three counts.

- [ ] **Step 8: Commit** (W) — message file `/tmp/…/b8.txt`:

```
feat(settings): every config row says who changed it last and when, and a refused key writes nothing

B8 (Feedback Round 1 / WP10). The stamp lives in a second per-session Store beside the
values (config.changed), so it is persisted exactly as they are. PUT /v1/config now
checks every key before writing any, audits CONFIG_SET with from/to, and stamps only
keys whose value moved.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add backend/tests/test_settings_changed_by.py && git commit -F /tmp/…/b8.txt -- backend/app/config.py backend/app/routers/settings.py backend/tests/test_settings_changed_by.py`

---

### Task B9: the settings page as grouped forms

**Files:**
- Modify: `frontend/src/screens/Settings.jsx` — imports `:1-9`; one effect after `:65`; the configuration section `:197-319` replaced; three helpers inserted before the `// LOCKED = held chip naming the decision (C3).` comment `:565`
- Modify: `frontend/src/i18n-admin.js` — 41 keys after `'set.title'` `:237` (EN) and `:802` (TH)
- Modify: `frontend/src/admin.css` — append
- Create: `frontend/src/screens/Settings.form.test.jsx`

**Interfaces:**
- Consumes: B8's `changed_by`, `changed_at` on each row; the existing `value`, `state`, `owner`, `editable`, `decision`, `decided_by`, `decided_on`, `ruling`; `fmtWhen` (`components/CaseContactDrawer.jsx:152`).
- Produces:
  - exports `CONFIG_GROUPS` and `groupConfig(config) -> [[group, keys]]` from `screens/Settings.jsx`.
  - Test ids, per key: `cfg-<key>` (the field, also `id="cfg-<key>"` and `data-state`), `cfg-edit-<key>`, `cfg-input-<key>`, `cfg-save-<key>`, `cfg-problem-<key>`, `cfg-open-<key>`, `cfg-decided-<key>`, `cfg-owner-only-<key>` (all kept); new `cfg-source-<key>`, `cfg-changed-<key>`, `cfg-lock-<key>`. Per group: `cfg-group-<group>`, where group is one of `penalty | reminders | npl | power | invoice | uninstall | bands | peak | other`.
  - The URL `/settings#cfg-<key>` scrolls that field into view once the rows load (P2's B5 link).
  - i18n keys (admin table): `set.group.<9 groups>`, `set.key.<16 keys>`, `set.unit.<9 keys>`, `set.source.ruling` `{ruling}`, `set.source.locked`, `set.source.set`, `set.changedBy` `{by}{at}`, `set.changedNever`, `set.lockedFor`.

**Pins:** `Settings.test.jsx` — the 16 tests and ids listed in the header; **measured 16/16 pass after this task: 0 edits**. Density: Settings has no census; Today untouched.

- [ ] **Step 1 (W):** `git log --oneline -3`. Grep the new keys across the four tables and `prefs.jsx`; expect no output:
`grep -n "'set\.key\.\|'set\.unit\.\|'set\.group\.\|'set\.source\.\|'set\.changed\|'set\.lockedFor" frontend/src/i18n-*.js frontend/src/prefs.jsx`

- [ ] **Step 2: Write the failing test** — create `frontend/src/screens/Settings.form.test.jsx`:

```jsx
// B9 (Feedback Round 1 / WP10): the settings page as grouped forms — label, value with
// unit, state chip, source line, lock icon, last-changed line.
import { fireEvent, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderIn } from '../test-utils.jsx'

const { mocks } = vi.hoisted(() => ({ mocks: {} }))
vi.mock('../api.js', () => ({
  api: {
    config: () => mocks.config(),
    putConfig: (payload) => mocks.putConfig(payload),
    dictionaries: () => Promise.resolve({ dictionaries: {}, history: [] }),
    bandSets: () => Promise.resolve({ active: 'OPERATIONAL', band_sets: [] }),
  },
}))

import Settings, { CONFIG_GROUPS, groupConfig } from './Settings.jsx'

const ROW = (over) => ({ value: '3', state: 'SET', owner: null, editable: true, editable_by: 'MANAGER',
                         changed_by: null, changed_by_role: null, changed_at: null, ...over })
const CONFIG = {
  config: {
    late_payment_daily_rate: ROW({ value: '0.0003', state: 'DECIDED', editable_by: 'OWNER', decision: 'CF1',
                                   decided_by: 'Arina', decided_on: '2026-09-09', ruling: 87 }),
    pipeline_lookahead_days: ROW({ changed_by: 'settasak', changed_by_role: 'MANAGER', changed_at: '2026-10-23T09:00:04' }),
    uninstall_fee_thb_per_watt: ROW({ value: '5' }),
    peak_write_mode: ROW({ value: 'DRAFT_ONLY', state: 'LOCKED', editable: false, editable_by: null }),
    brand_new_key: ROW({ value: 'x' }),
  },
  pending: {},
}

beforeEach(() => {
  window.localStorage.clear()
  mocks.config = () => Promise.resolve(CONFIG)
  mocks.putConfig = vi.fn(() => Promise.resolve(CONFIG))
})

describe('Settings form (B9)', () => {
  it('groups the keys under Thai headings, in the design order, and never drops an unfiled key', async () => {
    renderIn('th', <Settings />)
    const penalty = await screen.findByTestId('cfg-group-penalty')
    expect(within(penalty).getByText('ค่าปรับและผ่อนผัน')).toBeInTheDocument()
    expect(within(penalty).getByTestId('cfg-late_payment_daily_rate')).toBeInTheDocument()
    expect(within(screen.getByTestId('cfg-group-peak')).getByTestId('cfg-peak_write_mode')).toBeInTheDocument()
    expect(within(screen.getByTestId('cfg-group-other')).getByTestId('cfg-brand_new_key')).toBeInTheDocument()
    expect(groupConfig(CONFIG.config).map(([group]) => group)).toEqual(['penalty', 'invoice', 'uninstall', 'peak', 'other'])
    expect(CONFIG_GROUPS.map(([group]) => group)).toEqual(['penalty', 'reminders', 'npl', 'power', 'invoice', 'uninstall', 'bands', 'peak'])
  })

  it('a field reads label, value and unit, and keeps its key visible for traceability', async () => {
    renderIn('th', <Settings />)
    const field = await screen.findByTestId('cfg-uninstall_fee_thb_per_watt')
    expect(field).toHaveTextContent('ค่าถอดระบบ')
    expect(field).toHaveTextContent('5')
    expect(field).toHaveTextContent('บาทต่อวัตต์')
    expect(field).toHaveTextContent('uninstall_fee_thb_per_watt')
    expect(field).toHaveAttribute('id', 'cfg-uninstall_fee_thb_per_watt')
  })

  it('an unlabelled key falls back to the key itself, never to an i18n id', async () => {
    renderIn('en', <Settings />)
    const field = await screen.findByTestId('cfg-brand_new_key')
    expect(field).not.toHaveTextContent('set.key.')
    expect(field).not.toHaveTextContent('set.unit.')
  })

  it('the source line names the ruling on a decided key and the decision on a locked one', async () => {
    renderIn('en', <Settings />)
    expect(await screen.findByTestId('cfg-source-late_payment_daily_rate')).toHaveTextContent('Decision log · ruling 87')
    expect(screen.getByTestId('cfg-source-peak_write_mode')).toHaveTextContent('C3')
  })

  it('the last-changed line names who and when, or says the value is the shipped one', async () => {
    renderIn('th', <Settings />)
    expect(await screen.findByTestId('cfg-changed-pipeline_lookahead_days')).toHaveTextContent('แก้ไขล่าสุดโดย settasak เมื่อ 23/10/2026 09:00')
    expect(screen.getByTestId('cfg-changed-uninstall_fee_thb_per_watt')).toHaveTextContent('ยังไม่มีการแก้ไข')
  })

  it('a lock marks every field the caller may not edit, and no field they may', async () => {
    window.localStorage.setItem('volt.role', 'MANAGER')
    renderIn('en', <Settings />)
    const decided = await screen.findByTestId('cfg-late_payment_daily_rate')
    expect(within(decided).getByTestId('cfg-lock-late_payment_daily_rate')).toHaveAttribute('role', 'img')
    expect(within(screen.getByTestId('cfg-peak_write_mode')).getByTestId('cfg-lock-peak_write_mode')).toBeInTheDocument()
    expect(within(screen.getByTestId('cfg-pipeline_lookahead_days')).queryByTestId('cfg-lock-pipeline_lookahead_days')).toBeNull()
  })

  it('a link to /settings#cfg-<key> scrolls that field into view once the rows load', async () => {
    const scrolled = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function scrollIntoView() { scrolled.push(this.id) }
    window.location.hash = '#cfg-uninstall_fee_thb_per_watt'
    try {
      renderIn('th', <Settings />)
      await screen.findByTestId('cfg-uninstall_fee_thb_per_watt')
      expect(scrolled).toEqual(['cfg-uninstall_fee_thb_per_watt'])
    } finally {
      window.location.hash = ''
      Element.prototype.scrollIntoView = original
    }
  })

  it('the input is named by the field label while editing', async () => {
    window.localStorage.setItem('volt.role', 'MANAGER')
    renderIn('en', <Settings />)
    const field = await screen.findByTestId('cfg-pipeline_lookahead_days')
    fireEvent.click(within(field).getByTestId('cfg-edit-pipeline_lookahead_days'))
    expect(within(field).getByRole('textbox', { name: 'Invoice look-ahead' })).toHaveValue('3')
  })
})
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/screens/Settings.form.test.jsx`
Expected: FAIL — `groupConfig is not a function` (the import resolves to undefined), and `Unable to find an element by: [data-testid="cfg-group-penalty"]`.

- [ ] **Step 4: Implement** — in `frontend/src/screens/Settings.jsx`:

(a) after `import { fromError } from '../problem.js'` (line 8) add

```jsx
import { fmtWhen } from '../components/CaseContactDrawer.jsx'
```

(b) directly after `  useEffect(() => { loadConfig(); loadDicts(); loadBandSets() }, [loadConfig, loadDicts, loadBandSets])` (line 65) add

```jsx
  // B9: the case page's "แก้ไขที่ตั้งค่า" link (B5) lands on /settings#cfg-<key>. The
  // router does not scroll to a hash, and the field only exists once the rows load.
  useEffect(() => {
    if (config === null) return
    const hash = typeof window !== 'undefined' ? window.location.hash : ''
    if (!hash.startsWith('#cfg-')) return
    const field = document.getElementById(hash.slice(1))
    if (field && typeof field.scrollIntoView === 'function') field.scrollIntoView({ block: 'center' })
  }, [config])
```

(c) delete every line from `      {/* --- configuration ------------------------------------------------- */}` (line 197) down to, **not** including, `      {/* --- dictionaries -------------------------------------------------- */}` (line 321). Put this in their place, followed by one blank line before the dictionaries comment:

```jsx
      {/* --- configuration ------------------------------------------------- */}
      {/* B9 (Feedback Round 1 / WP10): the config rows as grouped forms — one field per
          key: label, value or input with its unit, the state chip, the source line, a
          lock when this role may not edit it, and who changed it last. Every test id
          the table carried (cfg-, cfg-edit-, cfg-input-, cfg-save-, cfg-problem-,
          cfg-open-, cfg-decided-, cfg-owner-only-) stays on the same fact. */}
      <section className="card ad-section" aria-labelledby="set-config">
        <h2 className="ad-h2" id="set-config">{t('set.config')}</h2>
        {!canEdit && <p className="ad-quiet">{t('set.readOnly')}</p>}
        {groupConfig(config).map(([group, keys]) => (
          <fieldset key={group} className="ad-cfg-group" data-testid={`cfg-group-${group}`}>
            <legend className="ad-cfg-group__title">{t(`set.group.${group}`)}</legend>
            {keys.map((key) => (
              <ConfigField key={key} fieldKey={key} row={config[key]} t={t} role={role} canEdit={canEdit}
                           editing={editing} setEditing={setEditing} bandSets={bandSets}
                           problem={rowProblems[key]} clearProblem={() => setRowProblems((p) => ({ ...p, [key]: null }))}
                           onSave={() => saveConfig(key)} />
            ))}
          </fieldset>
        ))}
        {Object.keys(pending).length > 0 && (
          <details className="ad-details">
            <summary>{t('set.pending')}</summary>
            <ul className="ad-list">
              {Object.entries(pending).map(([key, p]) => (
                <li key={key}>
                  <code>{key}</code> · <PendingBadge decision={p.decision} owner={p.owner} /> <span className="ad-owner">{p.owner}</span> · <span className="jy-source">{p.state}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
```

(d) immediately above the comment line `// LOCKED = held chip naming the decision (C3). OPEN = the register's violet with` (line 565), insert:

```jsx

// B9: the order a Manager thinks about the knobs, not the order the API lists them.
// A key the API serves that no group names still renders, under "other" — a new key
// must never vanish from the screen because nobody filed it.
export const CONFIG_GROUPS = [
  ['penalty', ['late_payment_daily_rate', 'late_payment_grace_days', 'penalty_invoicing_enabled']],
  ['reminders', ['reminder_offsets_days', 'review_sla_hours']],
  ['npl', ['npl_review_dpd', 'npl_review_missed_no_contact']],
  ['power', ['power_restriction_enabled', 'power_restriction_approver', 'power_restriction_min_missed',
             'power_restriction_require_broken_ptp']],
  ['invoice', ['invoice_owner_role', 'pipeline_lookahead_days']],
  ['uninstall', ['uninstall_fee_thb_per_watt']],
  ['bands', ['band_set_code']],
  ['peak', ['peak_write_mode']],
]

export function groupConfig(config) {
  const named = new Set(CONFIG_GROUPS.flatMap(([, keys]) => keys))
  const groups = CONFIG_GROUPS
    .map(([group, keys]) => [group, keys.filter((key) => config[key])])
    .filter(([, keys]) => keys.length > 0)
  const other = Object.keys(config).filter((key) => !named.has(key))
  return other.length > 0 ? [...groups, ['other', other]] : groups
}

// A label or unit the tables do not carry falls back to the key itself (label) or to
// nothing (unit) — never to the raw i18n id.
function optional(t, id) {
  const text = t(id)
  return text === id ? null : text
}

function LockMark({ t, testid }) {
  return (
    <span className="ad-cfg__lock" role="img" aria-label={t('set.lockedFor')} data-testid={testid}>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="3.5" y="7" width="9" height="6.5" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    </span>
  )
}

function ConfigField({ fieldKey: key, row, t, role, canEdit, editing, setEditing, bandSets, problem, clearProblem, onSave }) {
  const isEditing = editing && editing.key === key
  // An OPEN decision (nobody has closed it) and a DECIDED one (ruling 87/88,
  // Owner-tunable) are both Owner-only. SET keys keep the Manager/Owner rule.
  const ownerOnly = row.state === 'OPEN' || row.state === 'DECIDED'
  const showEdit = row.editable && canEdit && row.state !== 'LOCKED' && (!ownerOnly || role === 'OWNER')
  const label = optional(t, `set.key.${key}`) || key
  const unit = optional(t, `set.unit.${key}`)
  const labelId = `cfg-label-${key}`
  const sets = bandSets?.band_sets || []
  return (
    <div className="ad-cfg" id={`cfg-${key}`} data-testid={`cfg-${key}`} data-state={row.state}>
      <div className="ad-cfg__head">
        <span className="ad-cfg__label" id={labelId}>{label}</span>
        <code className="ad-cfg__key">{key}</code>
        <StateChip row={row} t={t} />
        {!showEdit && <LockMark t={t} testid={`cfg-lock-${key}`} />}
      </div>
      <div className="ad-cfg__value">
        {isEditing ? (
          key === 'band_set_code' ? (
            // S2-01: the active band set is CHOSEN from the sets on record, never
            // typed — a mistyped code took down the whole desk.
            <span className="jy-actions">
              <select className="ad-select" data-testid={`cfg-input-${key}`} aria-labelledby={labelId}
                      value={editing.value} disabled={sets.length === 0}
                      onChange={(e) => setEditing({ key, value: e.target.value })}>
                {!sets.some((bs) => bs.code === editing.value) && <option value={editing.value}>{editing.value || '—'}</option>}
                {sets.filter((bs) => bs.active !== false).map((bs) => (
                  <option key={bs.code} value={bs.code}>{bs.code}</option>
                ))}
              </select>
              <span className="ad-quiet" data-testid="band-set-code-why">
                {sets.length ? t('set.bandSetSelect') : t('set.bandSetSelectNone')}
              </span>
            </span>
          ) : (
            <input className="ad-input ad-input--code" data-testid={`cfg-input-${key}`} aria-labelledby={labelId}
                   value={editing.value} onChange={(e) => setEditing({ key, value: e.target.value })} />
          )
        ) : (
          <span className="ad-mono ad-cfg__shown">{row.value ?? '—'}</span>
        )}
        {unit && <span className="ad-cfg__unit">{unit}</span>}
        {showEdit && !isEditing && (
          <button type="button" className="btn btn--sm" data-testid={`cfg-edit-${key}`}
                  onClick={() => { setEditing({ key, value: row.value ?? '' }); clearProblem() }}>
            {t('set.edit')}
          </button>
        )}
        {showEdit && isEditing && (
          <span className="jy-actions">
            <button type="button" className="btn btn--sm btn--primary" data-testid={`cfg-save-${key}`} onClick={onSave}>
              {t('set.save')}
            </button>
            <button type="button" className="btn btn--sm" onClick={() => setEditing(null)}>{t('set.cancel')}</button>
          </span>
        )}
      </div>
      <p className="ad-cfg__source" data-testid={`cfg-source-${key}`}>
        {row.state === 'OPEN' && (
          <span data-testid={`cfg-open-${key}`}>{t('set.openRow', { owner: row.owner || '—' })}</span>
        )}
        {row.state === 'DECIDED' && (
          <>
            <span data-testid={`cfg-decided-${key}`}>{t('set.decidedRow', {
              by: row.decided_by || '—', on: row.decided_on || '—', decision: row.decision || '—',
            })}</span>
            {row.ruling ? ` · ${t('set.source.ruling', { ruling: row.ruling })}` : null}
          </>
        )}
        {row.state === 'LOCKED' && t('set.source.locked')}
        {row.state === 'SET' && t('set.source.set')}
        {/* set.ownerOnly names an OPEN decision by that word; a DECIDED row's own chip
            already says the Owner still tunes it (ruling 100), so this stays OPEN-only. */}
        {row.state === 'OPEN' && row.editable && canEdit && role !== 'OWNER' && (
          <span data-testid={`cfg-owner-only-${key}`}> · {t('set.ownerOnly')}</span>
        )}
      </p>
      <p className="ad-cfg__changed" data-testid={`cfg-changed-${key}`}>
        {row.changed_by
          ? t('set.changedBy', { by: row.changed_by, at: fmtWhen(row.changed_at) })
          : t('set.changedNever')}
      </p>
      {problem && (
        <div className="ad-cfg__problem" data-testid={`cfg-problem-${key}`}>
          <Problem problem={problem} endpoint="PUT /v1/config" />
        </div>
      )}
    </div>
  )
}
```

`StateChip` (below the insertion) is unchanged and still used.

(e) `frontend/src/i18n-admin.js` — directly after `  'set.title': 'Settings',` (line 237) insert:

```js
  // --- B9 (Feedback Round 1 / WP10): the settings form ---
  'set.group.penalty': 'Penalty and grace',
  'set.group.reminders': 'Reminders and review deadlines',
  'set.group.npl': 'NPL',
  'set.group.power': 'Power cut-off',
  'set.group.invoice': 'Invoices',
  'set.group.uninstall': 'Uninstall fee',
  'set.group.bands': 'Debt-age bands',
  'set.group.peak': 'PEAK (locked)',
  'set.group.other': 'Other settings',
  'set.key.late_payment_daily_rate': 'Late-payment penalty rate',
  'set.key.late_payment_grace_days': 'Grace before the penalty starts',
  'set.key.penalty_invoicing_enabled': 'Penalty invoicing',
  'set.key.reminder_offsets_days': 'Reminder days',
  'set.key.review_sla_hours': 'Time to answer a review request',
  'set.key.npl_review_dpd': 'NPL review starts at',
  'set.key.npl_review_missed_no_contact': 'NPL review after missed payments with no contact',
  'set.key.power_restriction_enabled': 'Power cut-off',
  'set.key.power_restriction_approver': 'Who approves a cut-off',
  'set.key.power_restriction_min_missed': 'Missed payments before a cut-off',
  'set.key.power_restriction_require_broken_ptp': 'A cut-off needs a broken promise',
  'set.key.invoice_owner_role': 'Who owns invoicing',
  'set.key.pipeline_lookahead_days': 'Invoice look-ahead',
  'set.key.uninstall_fee_thb_per_watt': 'Uninstall fee',
  'set.key.band_set_code': 'Band set in use',
  'set.key.peak_write_mode': 'PEAK write mode',
  'set.unit.late_payment_daily_rate': 'share of arrears per day',
  'set.unit.late_payment_grace_days': 'days',
  'set.unit.reminder_offsets_days': 'days before the due date',
  'set.unit.review_sla_hours': 'hours',
  'set.unit.npl_review_dpd': 'days past due',
  'set.unit.npl_review_missed_no_contact': 'missed payments',
  'set.unit.power_restriction_min_missed': 'missed payments',
  'set.unit.pipeline_lookahead_days': 'days',
  'set.unit.uninstall_fee_thb_per_watt': 'THB per watt',
  'set.source.ruling': 'Decision log · ruling {ruling}',
  'set.source.locked': 'Locked by decision C3 — PEAK receives drafts only',
  'set.source.set': 'System setting',
  'set.changedBy': 'Last changed by {by} on {at}',
  'set.changedNever': 'Not changed yet — this is the shipped value',
  'set.lockedFor': 'Your role cannot edit this',
```

and directly after `  'set.title': 'ตั้งค่า',` (line 802 at b5bdc7c; re-find it by that string) insert:

```js
  // --- B9 (Feedback Round 1 / WP10): ฟอร์มตั้งค่า ---
  'set.group.penalty': 'ค่าปรับและผ่อนผัน',
  'set.group.reminders': 'การเตือนและกำหนดเวลาตอบ',
  'set.group.npl': 'NPL',
  'set.group.power': 'การตัดไฟ',
  'set.group.invoice': 'ใบแจ้งหนี้',
  'set.group.uninstall': 'ค่าถอด',
  'set.group.bands': 'ช่วงอายุหนี้',
  'set.group.peak': 'PEAK (ล็อก)',
  'set.group.other': 'ค่าอื่น ๆ',
  'set.key.late_payment_daily_rate': 'อัตราค่าปรับชำระล่าช้า',
  'set.key.late_payment_grace_days': 'ระยะผ่อนผันก่อนเริ่มคิดค่าปรับ',
  'set.key.penalty_invoicing_enabled': 'ออกใบแจ้งหนี้ค่าปรับ',
  'set.key.reminder_offsets_days': 'วันส่งการเตือน',
  'set.key.review_sla_hours': 'เวลาตอบคำขอตรวจ',
  'set.key.npl_review_dpd': 'เริ่มพิจารณา NPL เมื่อค้าง',
  'set.key.npl_review_missed_no_contact': 'พิจารณา NPL เมื่อขาดชำระและติดต่อไม่ได้',
  'set.key.power_restriction_enabled': 'การตัดไฟ',
  'set.key.power_restriction_approver': 'ผู้อนุมัติการตัดไฟ',
  'set.key.power_restriction_min_missed': 'ขาดชำระกี่งวดจึงตัดไฟได้',
  'set.key.power_restriction_require_broken_ptp': 'ต้องผิดนัดชำระก่อนจึงตัดไฟได้',
  'set.key.invoice_owner_role': 'ผู้รับผิดชอบการออกใบแจ้งหนี้',
  'set.key.pipeline_lookahead_days': 'ดูใบแจ้งหนี้ล่วงหน้า',
  'set.key.uninstall_fee_thb_per_watt': 'ค่าถอดระบบ',
  'set.key.band_set_code': 'ชุดช่วงอายุหนี้ที่ใช้',
  'set.key.peak_write_mode': 'โหมดการส่งข้อมูลไป PEAK',
  'set.unit.late_payment_daily_rate': 'สัดส่วนของยอดค้างต่อวัน',
  'set.unit.late_payment_grace_days': 'วัน',
  'set.unit.reminder_offsets_days': 'วันก่อนครบกำหนด',
  'set.unit.review_sla_hours': 'ชั่วโมง',
  'set.unit.npl_review_dpd': 'วันหลังครบกำหนด',
  'set.unit.npl_review_missed_no_contact': 'งวดที่ขาดชำระ',
  'set.unit.power_restriction_min_missed': 'งวดที่ขาดชำระ',
  'set.unit.pipeline_lookahead_days': 'วัน',
  'set.unit.uninstall_fee_thb_per_watt': 'บาทต่อวัตต์',
  'set.source.ruling': 'บันทึกการตัดสินใจ · ข้อ {ruling}',
  'set.source.locked': 'ล็อกโดยการตัดสินใจ C3 — PEAK รับเฉพาะฉบับร่าง',
  'set.source.set': 'ค่าที่ระบบกำหนด',
  'set.changedBy': 'แก้ไขล่าสุดโดย {by} เมื่อ {at}',
  'set.changedNever': 'ยังไม่มีการแก้ไข — เป็นค่าตั้งต้นของระบบ',
  'set.lockedFor': 'บทบาทของคุณแก้ไขค่านี้ไม่ได้',
```

(f) append to `frontend/src/admin.css`:

```css
/* --- B9 (Feedback Round 1 / WP10): the settings form. Tokens for colour, border and
   type; literal px for spacing (tokens.css has no spacing scale). --- */
.ad-cfg-group { border: 0; margin: 0; padding: 0; min-width: 0; display: flex; flex-direction: column; }
.ad-cfg-group__title { font: var(--body-strong-14); color: var(--ink-800); padding: 12px 0 4px; }
.ad-cfg { display: flex; flex-direction: column; gap: 4px; padding: 10px 0; border-top: 1px solid var(--line-default); min-width: 0; }
.ad-cfg__head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ad-cfg__label { font: var(--label-13); color: var(--ink-900); }
.ad-cfg__key { font-family: var(--font-mono); font-size: 11px; color: var(--ink-500); }
.ad-cfg__lock { display: inline-flex; width: 16px; height: 16px; color: var(--ink-500); }
.ad-cfg__lock svg { width: 16px; height: 16px; }
.ad-cfg__value { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 32px; }
.ad-cfg__shown { font-size: 14px; color: var(--ink-900); }
.ad-cfg__unit { font: var(--caption-12); color: var(--ink-600); }
.ad-cfg__source, .ad-cfg__changed { margin: 0; font: var(--caption-12); color: var(--ink-500); }
.ad-cfg__problem { margin-top: 4px; }
```

The now-unused `set.col.*` keys stay: removing them would churn both tables for nothing.

- [ ] **Step 5: Run the new tests, the pinned file and the parity test**

Run: `cd frontend && npx vitest run src/screens/Settings.form.test.jsx src/screens/Settings.test.jsx src/i18n.test.js`
Expected: **8 + 16 + 19 = 43 passed** (measured in the scratch copy: Settings.form 8, Settings 16, i18n 19).

- [ ] **Step 6: Run the suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; frontend = baseline + 8 tests, + 1 file. Paste the counts.

- [ ] **Step 7: Commit** (W):

```
feat(settings): config rows become grouped forms with label, unit, state, source, lock and last change

B9 (Feedback Round 1 / WP10). Every test id the table carried stays on the same fact;
/settings#cfg-<key> scrolls to the field (the case header's settings link, B5). A key
no group names renders under "other", so it can never vanish.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add frontend/src/screens/Settings.form.test.jsx && git commit -F /tmp/…/b9.txt -- frontend/src/screens/Settings.jsx frontend/src/screens/Settings.form.test.jsx frontend/src/i18n-admin.js frontend/src/admin.css`

---
### Task B10a: `records.user_account` and the store — `app/user_accounts.py`

**Files:**
- Modify: `backend/app/schema.sql` — append after line 274
- Create: `backend/app/user_accounts.py`
- Create: `backend/tests/test_user_accounts.py`

**Interfaces:**
- Consumes: `db.configured()`, `db.connect()`, `db.DatabaseUnreachable` (db.py:32-101); `errors.Problem`, `errors.validation_failed`, `errors.not_found`; `audit.describe`.
- Produces (all used by B10b, B12a):
  - Table `records.user_account(id bigserial, kind 'GOOGLE'|'TEST', email, username, role, officer, display_name, invited_by, invited_at, disabled_at, disabled_by)`; unique partial indexes on `email` and on `username`.
  - `user_accounts.allow_entry(email, seed, fresh=True) -> ({"role","officer"}, "ACTIVE") | (None, "DISABLED") | (None, None)` — the merge rule.
  - `user_accounts.session_allowed(session, seed) -> bool` — cached (`CACHE_SECONDS = 30`); True for every non-GOOGLE session.
  - `user_accounts.display_name_for(session, fresh=True) -> {"display_name", "display_name_source", "display_name_fallback"}`.
  - `user_accounts.listed(seed, viewer_sub) -> [{"uid","email","role","officer","display_name","state","seeded","invited_by","invited_at","disabled_by","disabled_at","self"}]`.
  - `user_accounts.invite(seed, body, by, actor_role, officer_uids) -> listed row`; `disable(seed, uid, by, actor_role, actor_sub) -> listed row`; `set_profile(session, body) -> name|None`; `refresh() -> int`; `reset()`, `forget()`.
  - Constants `RANK`, `ADMIN_ROLES`, `NOT_DURABLE_TH`.
  - Audit acts `USER_INVITED` (detail `{role, officer, reenabled}`), `USER_DISABLED` (detail `{role, seeded}`), `PROFILE_SET` (detail `{display_name: "set"|"cleared"}`); subject `("user_account", <email or username>)`.
  - Refusals (code · status · error_id · message_th):
    - `user_list_unreachable` · 503 · DEBT-AUTH-506 · "อ่านรายชื่อผู้ใช้จากฐานข้อมูลไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง" (retryable)
    - `forbidden` · 403 · DEBT-IAM-0403 · "เฉพาะผู้จัดการหรือเจ้าของระบบจัดการรายชื่อผู้ใช้ได้"
    - `identity_not_fixed` · 403 · DEBT-AUTH-411 · "บัญชีที่สลับบทบาทได้จัดการผู้ใช้ไม่ได้ กรุณาเข้าสู่ระบบด้วยบัญชีของผู้จัดการหรือเจ้าของระบบ"
    - `role_above_actor` · 403 · DEBT-AUTH-412 · "จัดการผู้ใช้ที่มีบทบาทสูงกว่าตัวเองไม่ได้"
    - `cannot_disable_self` · 409 · DEBT-AUTH-413 · "ปิดการใช้งานบัญชีของตัวเองไม่ได้"
    - `user_exists` · 409 · DEBT-AUTH-414 · "อีเมลนี้มีสิทธิ์ใช้ระบบอยู่แล้ว"
    - `user_already_disabled` · 409 · DEBT-AUTH-415 · "บัญชีนี้ถูกปิดการใช้งานอยู่แล้ว เชิญใหม่เพื่อเปิดใช้อีกครั้ง"
    - `not_found` · 404 · DEBT-PLT-0404 · "ไม่พบข้อมูลที่ร้องขอ" (an unknown uid)
    - `validation_failed` · 422 · DEBT-PLT-0422, with `errors[].code`: `email_invalid` "อีเมลไม่ถูกต้อง", `role_unknown` "บทบาทไม่ถูกต้อง เลือกจากรายการ", `officer_unknown` "ไม่พบเจ้าหน้าที่คนนี้ในรายชื่อ", `display_name_invalid` "ชื่อที่แสดงต้องเป็นข้อความ" / "ชื่อที่แสดงยาวได้ไม่เกิน 60 ตัวอักษร และห้ามมีอักขระควบคุม", `not_editable` "ตั้งค่าได้เฉพาะชื่อที่แสดง"

**Pins:** 0 — a new module and a new table. `tests/test_landing_schema.py` and `tests/test_migrate_splitter.py` pass with the appended DDL (measured). Density: not a screen.

- [ ] **Step 1 (W):** `git log --oneline -3`. Use `<task-db>` for every run; the DB-backed test commits and deletes its own rows (`pg_conn` truncates only `landing` and `app`).

- [ ] **Step 2: Write the failing test** — create `backend/tests/test_user_accounts.py`:

```python
"""B10a (Feedback Round 1 / WP10, design F13/F14): records.user_account merged over the
AUTH_ALLOWLIST seed — the store alone, no HTTP.

Synthetic addresses only (PDPA ruling I4 of Round A): example.co.th, never a real person.
"""
import pytest
from sqlalchemy import text

from app import db, errors, migrate, user_accounts

SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
        "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
        "thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}
OFFICERS = {"owner", "settasak", "thip", "nantapol", "ops"}


@pytest.fixture(autouse=True)
def _clean():
    user_accounts.reset()
    yield
    user_accounts.reset()


def _problem(call):
    with pytest.raises(errors.Problem) as caught:
        call()
    return caught.value


def test_with_no_rows_the_seed_decides():
    assert user_accounts.allow_entry("thip@example.co.th", SEED) == ({"role": "OFFICER", "officer": "thip"}, "ACTIVE")
    assert user_accounts.allow_entry("stranger@example.co.th", SEED) == (None, None)


def test_an_invitation_adds_a_person_the_seed_never_named():
    user = user_accounts.invite(SEED, {"email": " New.Person@Example.co.th ", "role": "officer", "officer": "nantapol"},
                                "settasak", "MANAGER", OFFICERS)
    assert user["email"] == "new.person@example.co.th" and user["role"] == "OFFICER" and user["state"] == "ACTIVE"
    assert user["seeded"] is False and user["invited_by"] == "settasak" and user["invited_at"]
    assert user_accounts.allow_entry("new.person@example.co.th", SEED) == ({"role": "OFFICER", "officer": "nantapol"}, "ACTIVE")


def test_an_invitation_is_checked_field_by_field():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "nope", "role": "KING", "officer": "ghost"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert problem.status == 422
    assert [e["code"] for e in problem.errors] == ["email_invalid", "role_unknown", "officer_unknown"]
    assert all(e["message_th"] for e in problem.errors)


def test_nobody_invites_above_their_own_role():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "x@example.co.th", "role": "OWNER", "officer": "owner"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert (problem.status, problem.code) == (403, "role_above_actor")
    # an equal role is not above
    assert user_accounts.invite(SEED, {"email": "y@example.co.th", "role": "MANAGER", "officer": "settasak"},
                                "settasak", "MANAGER", OFFICERS)["role"] == "MANAGER"


def test_an_address_that_may_already_sign_in_is_not_invited_twice():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"},
                                                    "owner", "OWNER", OFFICERS))
    assert (problem.status, problem.code) == (409, "user_exists")
    assert "thip@" not in problem.detail and "thip@" not in problem.message_th


def test_a_disabled_row_wins_over_the_seed_and_an_invitation_brings_it_back():
    listed = {u["email"]: u for u in user_accounts.listed(SEED, None)}
    seed_uid = listed["thip@example.co.th"]["uid"]
    assert seed_uid.startswith("env-") and "thip" not in seed_uid
    user = user_accounts.disable(SEED, seed_uid, "settasak", "MANAGER", "lead@example.co.th")
    assert user["state"] == "DISABLED" and user["seeded"] is True and user["disabled_by"] == "settasak"
    assert user_accounts.allow_entry("thip@example.co.th", SEED) == (None, "DISABLED")
    again = user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "SUPERVISOR", "officer": "thip"},
                                 "settasak", "MANAGER", OFFICERS)
    assert again["state"] == "ACTIVE" and again["role"] == "SUPERVISOR"
    assert user_accounts.allow_entry("thip@example.co.th", SEED)[0]["role"] == "SUPERVISOR"


def test_the_seed_cannot_be_deleted_only_disabled():
    assert not [name for name in dir(user_accounts) if "delete" in name.lower() or "remove" in name.lower()]
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "boss@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "lead@example.co.th")
    user_accounts.reset()                               # a restart with no database
    assert "boss@example.co.th" in {u["email"] for u in user_accounts.listed(SEED, None)}


def test_a_manager_cannot_disable_an_owner_or_themselves():
    rows = {u["email"]: u["uid"] for u in user_accounts.listed(SEED, None)}
    problem = _problem(lambda: user_accounts.disable(SEED, rows["boss@example.co.th"], "settasak", "MANAGER", "lead@example.co.th"))
    assert (problem.status, problem.code) == (403, "role_above_actor")
    problem = _problem(lambda: user_accounts.disable(SEED, rows["lead@example.co.th"], "settasak", "MANAGER", "lead@example.co.th"))
    assert (problem.status, problem.code) == (409, "cannot_disable_self")
    problem = _problem(lambda: user_accounts.disable(SEED, rows["boss@example.co.th"], "owner", "OWNER", "boss@example.co.th"))
    assert problem.code == "cannot_disable_self"


def test_disabling_twice_and_an_unknown_uid_are_refused():
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
    assert _problem(lambda: user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")).code == "user_already_disabled"
    assert _problem(lambda: user_accounts.disable(SEED, "env-0000000000000000", "owner", "OWNER", "x")).status == 404
    assert _problem(lambda: user_accounts.disable(SEED, "999", "owner", "OWNER", "x")).status == 404


def test_a_session_ends_when_its_person_is_disabled_dropped_or_re_invited_differently():
    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    assert user_accounts.session_allowed(session, SEED) is True
    assert user_accounts.session_allowed(session, {}) is False                 # dropped from the seed
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
    assert user_accounts.session_allowed(session, SEED) is False
    user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "SUPERVISOR", "officer": "thip"}, "owner", "OWNER", OFFICERS)
    assert user_accounts.session_allowed(session, SEED) is False               # role changed since sign-in
    assert user_accounts.session_allowed({"sub": "manager.test", "kind": "TEST", "role": "MANAGER"}, {}) is True


def test_the_session_check_reads_a_cache_that_expires(monkeypatch):
    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    clock = [1000.0]
    monkeypatch.setattr(user_accounts, "_clock", lambda: clock[0])
    assert user_accounts.session_allowed(session, SEED) is True
    reads = []
    real = user_accounts._read_rows
    monkeypatch.setattr(user_accounts, "_read_rows", lambda: reads.append(1) or real())
    user_accounts.session_allowed(session, SEED)
    assert reads == []
    clock[0] += user_accounts.CACHE_SECONDS + 1
    user_accounts.session_allowed(session, SEED)
    assert reads == [1]


def test_a_display_name_is_set_cleared_and_checked():
    google = {"sub": "thip@example.co.th", "kind": "GOOGLE"}
    test = {"sub": "manager.test", "kind": "TEST"}
    assert user_accounts.display_name_for(google) == {"display_name": "thip", "display_name_source": "EMAIL",
                                                      "display_name_fallback": "thip"}
    assert user_accounts.display_name_for(test)["display_name_source"] == "USERNAME"
    assert user_accounts.set_profile(google, {"display_name": "  ทิพย์   อักษร "}) == "ทิพย์ อักษร"
    assert user_accounts.display_name_for(google) == {"display_name": "ทิพย์ อักษร", "display_name_source": "PROFILE",
                                                      "display_name_fallback": "thip"}
    user_accounts.set_profile(test, {"display_name": "Somchai"})
    assert user_accounts.display_name_for(test)["display_name"] == "Somchai"
    assert user_accounts.set_profile(google, {"display_name": ""}) is None
    assert user_accounts.display_name_for(google)["display_name"] == "thip"
    for bad in ("x" * 61, "a\u200bb", 42):
        assert _problem(lambda: user_accounts.set_profile(google, {"display_name": bad})).errors[0]["code"] == "display_name_invalid"
    assert _problem(lambda: user_accounts.set_profile(google, {"display_name": "x", "role": "OWNER"})).errors[0]["code"] == "not_editable"


def test_a_display_name_row_never_grants_sign_in():
    stranger = {"sub": "stranger@example.co.th", "kind": "GOOGLE"}
    user_accounts.set_profile(stranger, {"display_name": "Nobody"})
    assert user_accounts.allow_entry("stranger@example.co.th", SEED) == (None, None)
    assert "stranger@example.co.th" not in {u["email"] for u in user_accounts.listed(SEED, None)}


def test_a_configured_database_that_does_not_answer_refuses(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)
    problem = _problem(lambda: user_accounts.allow_entry("thip@example.co.th", SEED))
    assert (problem.status, problem.code, problem.retryable) == (503, "user_list_unreachable", True)


def test_the_rows_are_durable_in_postgres(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"},
                             "settasak", "MANAGER", OFFICERS)
        uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
        user_accounts.disable(SEED, uid, "settasak", "MANAGER", "lead@example.co.th")
        user_accounts.set_profile({"sub": "manager.test", "kind": "TEST"}, {"display_name": "Somchai"})
        user_accounts.forget()
        rows = pg_conn.execute(text("select kind, email, username, role, disabled_at is not null as off, display_name "
                                    "from records.user_account order by id")).all()
        pg_conn.commit()
        assert [tuple(r) for r in rows] == [("GOOGLE", "new@example.co.th", None, "OFFICER", False, None),
                                            ("GOOGLE", "thip@example.co.th", None, None, True, None),
                                            ("TEST", None, "manager.test", None, False, "Somchai")]
        assert user_accounts.allow_entry("thip@example.co.th", SEED) == (None, "DISABLED")
        again = user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"},
                                     "settasak", "MANAGER", OFFICERS)
        assert again["state"] == "ACTIVE"
        assert _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER",
                                                           "officer": "nantapol"}, "settasak", "MANAGER", OFFICERS)).code == "user_exists"
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.user_account"))
        pg_conn.commit()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_user_accounts.py`
Expected: collection ERROR — `ImportError: cannot import name 'user_accounts' from 'app'`.

- [ ] **Step 4: The table** — append to `backend/app/schema.sql` (after `CREATE INDEX IF NOT EXISTS attachment_target_idx …`, line 274; if P2 or P5 appended first, append after theirs):

```sql

-- Feedback Round 1 / WP10 (design F13, F14): the allow-list people manage, merged over
-- the AUTH_ALLOWLIST seed, and each person's own display name. GOOGLE rows are keyed by
-- the lower-cased e-mail; TEST rows by the test-account username and carry only a
-- display name (password test accounts are unchanged). No row is ever deleted: a set
-- disabled_at refuses sign-in whatever the seed says.
CREATE TABLE IF NOT EXISTS records.user_account (
    id            bigserial   PRIMARY KEY,
    kind          text        NOT NULL CHECK (kind IN ('GOOGLE','TEST')),
    email         text,
    username      text,
    role          text        CHECK (role IN ('OFFICER','SUPERVISOR','MANAGER','OWNER','OPS')),
    officer       text,
    display_name  text,
    invited_by    text,
    invited_at    timestamptz,
    disabled_at   timestamptz,
    disabled_by   text,
    CONSTRAINT user_account_key_check CHECK (
        (kind = 'GOOGLE' AND email IS NOT NULL AND username IS NULL AND email = lower(email))
        OR (kind = 'TEST' AND username IS NOT NULL AND email IS NULL AND role IS NULL)),
    CONSTRAINT user_account_role_needs_officer CHECK (role IS NULL OR officer IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS user_account_email_idx    ON records.user_account (email)    WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_account_username_idx ON records.user_account (username) WHERE username IS NOT NULL;
```

`migrate.statements()` strips `--` lines before splitting, and no literal here holds a `;`.

- [ ] **Step 5: The store** — create `backend/app/user_accounts.py`:

```python
"""The allow-list people manage — records.user_account merged over AUTH_ALLOWLIST.

Feedback Round 1 / WP10 and WP11 (design F13, F14). The rules, each load-bearing:

  - The env AUTH_ALLOWLIST is the SEED. auth.load_config reads it at start-up and
    nothing writes it. A row here is merged over it: a row with a role replaces the
    seed's role and officer; a row with only a display name changes nothing about who
    may sign in.
  - A DISABLED row wins over everything, the seed included. There is no delete, so a
    seed entry can never be removed from a screen — only disabled, and a disabled
    entry comes back by being invited again.
  - Nobody hands out a role above their own, and nobody disables a role above their
    own or themselves.
  - E-mail addresses live in this table and in the audit subject only. Nothing here
    prints one, and no refusal's detail or message carries one.

Durable when a database is configured (schema records: survives a deploy); a process
dict labelled not-durable when it is not — the three states db.py names. A configured
database that does not answer refuses (503); it never falls back to the seed alone.

Sessions are stateless signed cookies, so ending a disabled person's session means the
login middleware asks session_allowed() on every request. It answers from a cache
refreshed at most every CACHE_SECONDS, and at once on the instance that made the
change: on another Cloud Run instance a disabled session ends within CACHE_SECONDS.
"""
import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import audit, db, errors

CACHE_SECONDS = 30
DISPLAY_NAME_MAX = 60
NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — รายชื่อนี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Who may hand out which role. OPS is the O&M team's seat, ranked with OFFICER.
RANK = {"OFFICER": 1, "OPS": 1, "SUPERVISOR": 2, "MANAGER": 3, "OWNER": 4}
ADMIN_ROLES = ("MANAGER", "OWNER")
COLUMNS = ("id", "kind", "email", "username", "role", "officer", "display_name",
           "invited_by", "invited_at", "disabled_at", "disabled_by")

_MEMORY = {}
_NEXT = {"id": 0}
_CACHE = {"at": None, "rows": None}
_clock = time.monotonic


def reset():
    """Test seam: the memory rows and the cache."""
    _MEMORY.clear()
    _NEXT["id"] = 0
    forget()


def forget():
    _CACHE["at"], _CACHE["rows"] = None, None


# --- refusals (RFC 9457) --------------------------------------------------------------

def list_unreachable():
    return errors.Problem("user_list_unreachable", 503, "The user list cannot be read",
                          "A database is configured and did not answer, so sign-in cannot be decided.",
                          "อ่านรายชื่อผู้ใช้จากฐานข้อมูลไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
                          "DEBT-AUTH-506", retryable=True)


def admin_only():
    return errors.Problem("forbidden", 403, "Manager or Owner only",
                          "Only a Manager or the Owner manages who may sign in.",
                          "เฉพาะผู้จัดการหรือเจ้าของระบบจัดการรายชื่อผู้ใช้ได้", "DEBT-IAM-0403")


def identity_not_fixed():
    return errors.Problem("identity_not_fixed", 403, "A switching account cannot manage users",
                          "This session may act as any role, so it cannot vouch for an invitation.",
                          "บัญชีที่สลับบทบาทได้จัดการผู้ใช้ไม่ได้ กรุณาเข้าสู่ระบบด้วยบัญชีของผู้จัดการหรือเจ้าของระบบ",
                          "DEBT-AUTH-411")


def role_above_actor(role):
    return errors.Problem("role_above_actor", 403, "That role is above your own",
                          "A %s cannot be invited or disabled by someone whose role ranks lower." % role,
                          "จัดการผู้ใช้ที่มีบทบาทสูงกว่าตัวเองไม่ได้", "DEBT-AUTH-412",
                          extensions={"role": role})


def cannot_disable_self():
    return errors.Problem("cannot_disable_self", 409, "You cannot disable yourself",
                          "Ask another Manager or the Owner.",
                          "ปิดการใช้งานบัญชีของตัวเองไม่ได้", "DEBT-AUTH-413")


def user_exists():
    return errors.Problem("user_exists", 409, "Already on the list",
                          "This e-mail may already sign in; disable it first to change it.",
                          "อีเมลนี้มีสิทธิ์ใช้ระบบอยู่แล้ว", "DEBT-AUTH-414")


def user_already_disabled():
    return errors.Problem("user_already_disabled", 409, "Already disabled",
                          "Invite the e-mail again to bring it back.",
                          "บัญชีนี้ถูกปิดการใช้งานอยู่แล้ว เชิญใหม่เพื่อเปิดใช้อีกครั้ง", "DEBT-AUTH-415")


def _invalid(pointer, code, message, message_th):
    return errors.validation_failed([{"pointer": pointer, "code": code, "message": message,
                                      "message_th": message_th}])


# --- reading ----------------------------------------------------------------------------

def _key(row):
    return (row["kind"], row["email"] if row["kind"] == "GOOGLE" else row["username"])


def _connect():
    try:
        return db.connect()
    except db.DatabaseUnreachable:
        raise list_unreachable()


def _read_rows():
    if not db.configured():
        return {_key(r): dict(r) for r in _MEMORY.values()}
    conn = _connect()
    try:
        with conn.begin():
            rows = conn.execute(text("select " + ", ".join(COLUMNS) + " from records.user_account order by id")).mappings().all()
    finally:
        conn.close()
    return {_key(r): dict(r) for r in rows}


def _rows(fresh):
    if fresh or _CACHE["rows"] is None or _clock() - _CACHE["at"] > CACHE_SECONDS:
        _CACHE["rows"], _CACHE["at"] = _read_rows(), _clock()
    return _CACHE["rows"]


def refresh():
    """The start-up merge: read the rows once so the first request needs no query."""
    return len(_rows(fresh=True))


def allow_entry(email, seed, fresh=True):
    """({role, officer}, "ACTIVE"), (None, "DISABLED") or (None, None) for an e-mail."""
    row = _rows(fresh).get(("GOOGLE", email))
    if row is not None and row["disabled_at"] is not None:
        return None, "DISABLED"
    if row is not None and row["role"]:
        return {"role": row["role"], "officer": row["officer"]}, "ACTIVE"
    entry = seed.get(email)
    return (dict(entry), "ACTIVE") if entry else (None, None)


def session_allowed(session, seed):
    """False when a Google session's person was disabled, dropped from the seed, or
    re-invited with another role or officer since signing in. A test account is not
    managed here (design F13: password test accounts are unchanged)."""
    if session.get("kind") != "GOOGLE":
        return True
    entry, _state = allow_entry(session.get("sub"), seed, fresh=False)
    return (entry is not None and entry["role"] == session.get("role")
            and entry["officer"] == session.get("officer"))


def display_name_for(session, fresh=True):
    """WP11: {display_name, display_name_source, display_name_fallback} — the person's
    own name (PROFILE), else the e-mail's user part (EMAIL), else the username
    (USERNAME). The fallback is served too, so no screen derives it from the subject."""
    kind = "GOOGLE" if session.get("kind") == "GOOGLE" else "TEST"
    sub = str(session.get("sub") or "")
    fallback, source = (sub.split("@", 1)[0], "EMAIL") if kind == "GOOGLE" else (sub, "USERNAME")
    row = _rows(fresh).get((kind, sub))
    if row is not None and row["display_name"]:
        return {"display_name": row["display_name"], "display_name_source": "PROFILE",
                "display_name_fallback": fallback}
    return {"display_name": fallback, "display_name_source": source, "display_name_fallback": fallback}


def _seed_uid(email):
    # A listed seed entry needs an id for its disable URL, and an e-mail in a URL would
    # land in every request log. A digest does not.
    return "env-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def listed(seed, viewer_sub):
    """The merged list a Manager reads: every seed e-mail and every GOOGLE row."""
    rows = _rows(fresh=True)
    out = []
    for email in sorted(set(seed) | {k[1] for k in rows if k[0] == "GOOGLE"}):
        row = rows.get(("GOOGLE", email))
        entry = seed.get(email)
        disabled = row is not None and row["disabled_at"] is not None
        if row is not None and row["role"]:
            role, officer = row["role"], row["officer"]
        elif entry:
            role, officer = entry["role"], entry["officer"]
        else:
            role, officer = None, None
        if role is None and not disabled:
            continue          # a display-name row for an e-mail no longer on any list
        out.append({
            "uid": str(row["id"]) if row is not None else _seed_uid(email),
            "email": email, "role": role, "officer": officer,
            "display_name": row["display_name"] if row is not None else None,
            "state": "DISABLED" if disabled else "ACTIVE",
            "seeded": entry is not None,
            "invited_by": row["invited_by"] if row is not None else None,
            "invited_at": _iso(row["invited_at"]) if row is not None else None,
            "disabled_by": row["disabled_by"] if row is not None else None,
            "disabled_at": _iso(row["disabled_at"]) if row is not None else None,
            "self": email == viewer_sub,
        })
    return out


def _resolve(uid, seed):
    rows = _rows(fresh=True)
    if uid.startswith("env-"):
        email = next((e for e in seed if _seed_uid(e) == uid), None)
    else:
        row = next((r for r in rows.values() if r["kind"] == "GOOGLE" and str(r["id"]) == uid), None)
        email = row["email"] if row else None
    return email


# --- writing ----------------------------------------------------------------------------

def _memory_row(kind, email=None, username=None):
    for row in _MEMORY.values():
        if _key(row) == (kind, email if kind == "GOOGLE" else username):
            return row
    _NEXT["id"] += 1
    row = dict.fromkeys(COLUMNS)
    row.update(id=_NEXT["id"], kind=kind, email=email, username=username)
    _MEMORY[row["id"]] = row
    return row


def _now():
    return datetime.now(timezone.utc)


def invite(seed, body, by, actor_role, officer_uids):
    email = str(body.get("email") or "").strip().lower()
    role = str(body.get("role") or "").strip().upper()
    officer = str(body.get("officer") or "").strip()
    problems = []
    if not EMAIL.match(email):
        problems.append({"pointer": "/email", "code": "email_invalid", "message": "not an e-mail address",
                         "message_th": "อีเมลไม่ถูกต้อง"})
    if role not in RANK:
        problems.append({"pointer": "/role", "code": "role_unknown",
                         "message": "role is one of %s" % ", ".join(sorted(RANK)),
                         "message_th": "บทบาทไม่ถูกต้อง เลือกจากรายการ"})
    if officer not in officer_uids:
        problems.append({"pointer": "/officer", "code": "officer_unknown",
                         "message": "officer is not in /v1/officers",
                         "message_th": "ไม่พบเจ้าหน้าที่คนนี้ในรายชื่อ"})
    if problems:
        raise errors.validation_failed(problems)
    if RANK[role] > RANK[actor_role]:
        raise role_above_actor(role)
    _entry, state = allow_entry(email, seed, fresh=True)
    if state == "ACTIVE":
        raise user_exists()
    audit.describe(act="USER_INVITED", subject=("user_account", email),
                   detail={"role": role, "officer": officer, "reenabled": state == "DISABLED"})
    if not db.configured():
        _memory_row("GOOGLE", email=email).update(role=role, officer=officer, invited_by=by, invited_at=_now(),
                                                   disabled_at=None, disabled_by=None)
    else:
        conn = _connect()
        try:
            with conn.begin():
                done = conn.execute(text(
                    "insert into records.user_account (kind, email, role, officer, invited_by, invited_at) "
                    "values ('GOOGLE', :e, :r, :o, :b, now()) "
                    "on conflict (email) where email is not null do update set role = excluded.role, "
                    "officer = excluded.officer, invited_by = excluded.invited_by, "
                    "invited_at = excluded.invited_at, disabled_at = null, disabled_by = null "
                    "where records.user_account.disabled_at is not null or records.user_account.role is null "
                    "returning id"), {"e": email, "r": role, "o": officer, "b": by}).first()
        except IntegrityError:
            raise user_exists()          # never the driver's text: it quotes the e-mail
        finally:
            conn.close()
        if done is None:
            raise user_exists()          # made active by someone else a moment ago
    forget()
    return next(u for u in listed(seed, None) if u["email"] == email)


def disable(seed, uid, by, actor_role, actor_sub):
    email = _resolve(uid, seed)
    entry, state = allow_entry(email, seed, fresh=False) if email else (None, None)
    if state is None:
        raise errors.not_found("user")
    if state == "DISABLED":
        raise user_already_disabled()
    if email == actor_sub:
        raise cannot_disable_self()
    if RANK[entry["role"]] > RANK[actor_role]:
        raise role_above_actor(entry["role"])
    audit.describe(act="USER_DISABLED", subject=("user_account", email),
                   detail={"role": entry["role"], "seeded": email in seed})
    if not db.configured():
        _memory_row("GOOGLE", email=email).update(disabled_at=_now(), disabled_by=by)
    else:
        conn = _connect()
        try:
            with conn.begin():
                conn.execute(text(
                    "insert into records.user_account (kind, email, disabled_at, disabled_by) "
                    "values ('GOOGLE', :e, now(), :b) "
                    "on conflict (email) where email is not null do update set disabled_at = now(), "
                    "disabled_by = excluded.disabled_by"), {"e": email, "b": by})
        finally:
            conn.close()
    forget()
    return next(u for u in listed(seed, actor_sub) if u["email"] == email)


def _clean_name(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("/display_name", "display_name_invalid", "a display name is text",
                       "ชื่อที่แสดงต้องเป็นข้อความ")
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > DISPLAY_NAME_MAX or any(unicodedata.category(c).startswith("C") for c in name):
        raise _invalid("/display_name", "display_name_invalid",
                       "at most %d characters, no control characters" % DISPLAY_NAME_MAX,
                       "ชื่อที่แสดงยาวได้ไม่เกิน %d ตัวอักษร และห้ามมีอักขระควบคุม" % DISPLAY_NAME_MAX)
    return name


def set_profile(session, body):
    unknown = sorted(set(body) - {"display_name"})
    if unknown:
        raise _invalid("/" + unknown[0], "not_editable", "only display_name is set here",
                       "ตั้งค่าได้เฉพาะชื่อที่แสดง")
    name = _clean_name(body.get("display_name"))
    kind = "GOOGLE" if session.get("kind") == "GOOGLE" else "TEST"
    sub = str(session.get("sub") or "")
    audit.describe(act="PROFILE_SET", subject=("user_account", sub),
                   detail={"display_name": "set" if name else "cleared"})
    if not db.configured():
        if kind == "GOOGLE":
            _memory_row(kind, email=sub)["display_name"] = name
        else:
            _memory_row(kind, username=sub)["display_name"] = name
    else:
        column = "email" if kind == "GOOGLE" else "username"
        conn = _connect()
        try:
            with conn.begin():
                conn.execute(text(
                    "insert into records.user_account (kind, %s, display_name) values (:k, :s, :n) "
                    "on conflict (%s) where %s is not null do update set display_name = excluded.display_name"
                    % (column, column, column)), {"k": kind, "s": sub, "n": name})
        finally:
            conn.close()
    forget()
    return name
```

Why each read opens `with conn.begin()`: production hands every call a fresh `db.connect()`, but the DB-backed test hands the same connection to several calls, and a bare `execute` would autobegin and make the next `conn.begin()` raise (the Task 21 lesson of Round A).

- [ ] **Step 6: Run the focused tests and the schema tests**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_user_accounts.py tests/test_landing_schema.py tests/test_migrate_splitter.py tests/test_auth_schema.py`
Expected: all pass; `test_user_accounts.py` **15 passed** (measured, the Postgres test included).

- [ ] **Step 7: Suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; backend = baseline + 15. Paste.

- [ ] **Step 8: Commit** (W):

```
feat(auth): records.user_account — the managed allow-list over the AUTH_ALLOWLIST seed, and display names

B10a (Feedback Round 1 / WP10, design F13/F14). A disabled row wins over the seed; a
role above the actor's is never granted or disabled; nobody disables themselves; no
delete exists. Durable in Postgres, labelled not-durable in memory, 503 when a
configured database does not answer. E-mails stay in the table and the audit subject.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add backend/app/user_accounts.py backend/tests/test_user_accounts.py && git commit -F /tmp/…/b10a.txt -- backend/app/schema.sql backend/app/user_accounts.py backend/tests/test_user_accounts.py`

---

### Task B10b: the user routes, the sign-in merge, and ending a withdrawn session

**Files:**
- Modify: `backend/app/auth.py` — two problems after `not_on_allow_list` `:312-316`; `OPEN_PREFIX` `:352` → `OPEN_PATHS`; `AuthMiddleware.__init__` `:396-399`; the open-path gate `:404-405`; after the `session is None` refusal `:411-414`
- Modify: `backend/app/routers/login.py` — docstring `:1`, imports `:5-8`, `google_login` `:78-81`, `me` `:91-94`, three routes appended
- Modify: `backend/app/main.py` — `_lifespan` `:55-67`; the login block `:257-265`
- Create: `backend/tests/test_auth_users.py`

**Interfaces:**
- Consumes: B10a's `allow_entry`, `session_allowed`, `listed`, `invite`, `disable`, `identity_not_fixed`, `admin_only`, `RANK`, `ADMIN_ROLES`, `NOT_DURABLE_TH`, `refresh`; `officers.registry()`; `routers.today.who`.
- Produces:
  - `GET /v1/auth/users` → `{"users": [listed rows], "grantable_roles": [roles in auth.ROLES order whose rank ≤ yours], "durable": bool, "note_th": str|null}`.
  - `POST /v1/auth/users` body `{"email","role","officer"}` → 201 `{"user": row}`.
  - `POST /v1/auth/users/{uid}:disable` → 200 `{"user": row}`.
  - All three: 404 `auth_off` with login off; 401 `auth_required` without a session; 403 `identity_not_fixed` for a switching session; 403 `forbidden` below Manager.
  - `auth.OPEN_PATHS` (tuple of five paths) replaces `auth.OPEN_PREFIX`.
  - `AuthMiddleware(app, request_id=…, roster=…, still_allowed=lambda session: True)`.
  - `auth.account_disabled()` · 403 · `account_disabled` · DEBT-AUTH-406 · "บัญชีนี้ถูกปิดการใช้งาน กรุณาติดต่อผู้จัดการหรือเจ้าของระบบ" — from `POST /v1/auth/google`.
  - `auth.session_withdrawn()` · 401 · code **`auth_required`** · DEBT-AUTH-407 · "สิทธิ์ใช้ระบบของบัญชีนี้ถูกยกเลิกหรือเปลี่ยนแปลง กรุณาเข้าสู่ระบบใหม่" · `extensions.reason = "account_withdrawn"` — from the middleware (with `Set-Cookie: volt_auth=; Max-Age=0`) and from `GET /v1/auth/me`.

**Pins:** 0. `test_auth_http.py` 25/25, `test_auth_core.py` 19/19, `test_audit_coverage.py` 4/4 pass unchanged (measured; `OPEN_PREFIX` is referenced by no test). The echo client at `test_auth_http.py:122` builds `AuthMiddleware(mini, roster=…)` without the new argument, so the default must stay `lambda session: True`. Density: not a screen.

- [ ] **Step 1 (W):** `git log --oneline -3`.

- [ ] **Step 2: Write the failing test** — create `backend/tests/test_auth_users.py`:

```python
"""B10b (Feedback Round 1 / WP10, design F13): the user list over HTTP — who may call
it, what sign-in does with it, and what a disabled person's cookie does next.

Login is switched on per test through auth.set_config (never backend/.env, never
os.environ). Synthetic addresses only.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth, user_accounts
from app.main import app

SECRET = "s" * 40
FAST = 1000
SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
        "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
        "thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}


def _accounts():
    return {
        "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
        "owner.test": {"hash": auth.hash_password("owner-pw", rounds=FAST), "role": "OWNER", "officer": "owner"},
        "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER", "officer": "settasak"},
        "officer.test": {"hash": auth.hash_password("officer-pw", rounds=FAST), "role": "OFFICER", "officer": "nantapol"},
    }


@pytest.fixture
def on(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(_accounts()),
               "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com", "AUTH_ALLOWLIST": json.dumps(SEED)}
    user_accounts.reset()
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _password(username, password):
    client = TestClient(app)
    assert client.post("/v1/auth/password", json={"username": username, "password": password}).status_code == 200
    return client


def _google(monkeypatch, email):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": email, "email_verified": True})
    client = TestClient(app)
    return client, client.post("/v1/auth/google", json={"credential": "tok"})


def _uid(client, email):
    return next(u["uid"] for u in client.get("/v1/auth/users").json()["users"] if u["email"] == email)


def test_with_login_off_every_user_route_answers_auth_off():
    client = TestClient(app)
    assert client.get("/v1/auth/users", headers={"X-Volt-Role": "OWNER"}).json()["code"] == "auth_off"
    assert client.post("/v1/auth/users", json={"email": "a@example.co.th"}, headers={"X-Volt-Role": "OWNER"}).status_code == 404
    assert client.post("/v1/auth/users/1:disable", headers={"X-Volt-Role": "OWNER"}).json()["code"] == "auth_off"


def test_the_user_routes_are_not_open_the_way_sign_in_is(on):
    client = TestClient(app)
    for call in (lambda: client.get("/v1/auth/users"), lambda: client.post("/v1/auth/users", json={}),
                 lambda: client.post("/v1/auth/users/1:disable", json={})):
        r = call()
        assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert client.get("/v1/auth/config").status_code == 200


def test_only_a_fixed_manager_or_owner_manages_users(on):
    officer = _password("officer.test", "officer-pw")
    r = officer.get("/v1/auth/users")
    assert (r.status_code, r.json()["code"]) == (403, "forbidden") and r.json()["message_th"]
    tester = _password("tester", "tester-pw")
    r = tester.get("/v1/auth/users", headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"})
    assert (r.status_code, r.json()["code"]) == (403, "identity_not_fixed")
    manager = _password("manager.test", "manager-pw")
    body = manager.get("/v1/auth/users").json()
    assert {u["email"] for u in body["users"]} == set(SEED)
    assert body["grantable_roles"] == ["OFFICER", "SUPERVISOR", "MANAGER", "OPS"]
    assert body["durable"] is False and body["note_th"]


def test_a_manager_invites_and_the_invited_person_signs_in_as_invited(on, monkeypatch):
    manager = _password("manager.test", "manager-pw")
    r = manager.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"})
    assert r.status_code == 201, r.json()
    assert r.json()["user"]["invited_by"] == "settasak" and r.json()["user"]["state"] == "ACTIVE"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["subject_type"], entry["subject_uid"]) == ("USER_INVITED", "user_account", "new@example.co.th")
    assert "new@example.co.th" not in json.dumps(entry["detail"])
    _client, signed = _google(monkeypatch, "new@example.co.th")
    assert signed.status_code == 200 and signed.json()["officer"] == "nantapol" and signed.json()["role"] == "OFFICER"


def test_an_invitation_above_the_inviters_role_is_refused(on):
    manager = _password("manager.test", "manager-pw")
    r = manager.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OWNER", "officer": "owner"})
    assert (r.status_code, r.json()["code"]) == (403, "role_above_actor") and r.json()["message_th"]


def test_a_bad_invitation_names_each_field(on):
    owner = _password("owner.test", "owner-pw")
    r = owner.post("/v1/auth/users", json={"email": "no", "role": "KING", "officer": "ghost"})
    assert r.status_code == 422 and [e["code"] for e in r.json()["errors"]] == ["email_invalid", "role_unknown", "officer_unknown"]


def test_a_manager_cannot_disable_an_owner_or_themselves(on, monkeypatch):
    lead, signed = _google(monkeypatch, "lead@example.co.th")
    assert signed.status_code == 200
    r = lead.post("/v1/auth/users/%s:disable" % _uid(lead, "boss@example.co.th"), json={})
    assert (r.status_code, r.json()["code"]) == (403, "role_above_actor")
    me = next(u for u in lead.get("/v1/auth/users").json()["users"] if u["self"])
    assert me["email"] == "lead@example.co.th"
    r = lead.post("/v1/auth/users/%s:disable" % me["uid"], json={})
    assert (r.status_code, r.json()["code"]) == (409, "cannot_disable_self") and r.json()["message_th"]


def test_a_disabled_person_cannot_sign_in_and_their_open_session_ends(on, monkeypatch):
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200 and thip.get("/v1/workbook").status_code == 200
    owner = _password("owner.test", "owner-pw")
    r = owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={})
    assert r.status_code == 200 and r.json()["user"]["state"] == "DISABLED"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["subject_uid"]) == ("USER_DISABLED", "thip@example.co.th")
    me = thip.get("/v1/auth/me")                       # open route: it checks for itself
    assert me.status_code == 401 and me.json()["extensions"]["reason"] == "account_withdrawn"
    ended = thip.get("/v1/workbook")
    assert ended.status_code == 401 and ended.json()["code"] == "auth_required"
    assert ended.json()["extensions"]["reason"] == "account_withdrawn"
    assert "Max-Age=0" in ended.headers["set-cookie"]
    _again, refused = _google(monkeypatch, "thip@example.co.th")
    assert (refused.status_code, refused.json()["code"]) == (403, "account_disabled") and refused.json()["message_th"]


def test_the_seed_has_no_delete_route_and_a_disabled_seed_comes_back_by_invitation(on, monkeypatch):
    from starlette.routing import Route
    for route in app.routes:
        if isinstance(route, Route) and route.path.startswith("/v1/auth/users"):
            assert not ({"DELETE"} & set(route.methods or ())), route.path
    owner = _password("owner.test", "owner-pw")
    owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={})
    r = owner.post("/v1/auth/users", json={"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"})
    assert r.status_code == 201 and r.json()["user"]["state"] == "ACTIVE" and r.json()["user"]["seeded"] is True
    _client, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200


def test_a_password_test_account_is_untouched_by_the_list(on):
    manager = _password("manager.test", "manager-pw")
    assert manager.get("/v1/workbook").status_code == 200
    assert "manager.test" not in {u["email"] for u in manager.get("/v1/auth/users").json()["users"]}


def test_a_database_that_does_not_answer_refuses_the_session_check(on, monkeypatch):
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200
    from app import db
    user_accounts.forget()
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)
    r = thip.get("/v1/auth/users")
    assert (r.status_code, r.json()["code"]) == (503, "user_list_unreachable")
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_auth_users.py`
Expected: 11 FAILED — every user route answers 404 `not_found` (no route), and the disabled Thip still signs in.

- [ ] **Step 4: `backend/app/auth.py`**

(a) directly after the `not_on_allow_list` function (ends `"DEBT-AUTH-403", extensions={"email": email})`, line 316), insert:

```python


def account_disabled():
    # Feedback Round 1 / WP10 (F13): a disabled row wins over the seed. Said plainly —
    # the person proved the address is theirs, so naming the state leaks nothing.
    return errors.Problem("account_disabled", 403, "This account is disabled",
                          "A Manager or the Owner disabled this e-mail on the user list.",
                          "บัญชีนี้ถูกปิดการใช้งาน กรุณาติดต่อผู้จัดการหรือเจ้าของระบบ",
                          "DEBT-AUTH-406")


def session_withdrawn():
    # The same code as auth_required ON PURPOSE: api.js signalAuth() brings the login
    # screen back on exactly that code, so a withdrawn session lands where an expired
    # one does. extensions.reason says which it was.
    return errors.Problem("auth_required", 401, "Sign in to continue",
                          "This account's access was withdrawn or changed since it signed in.",
                          "สิทธิ์ใช้ระบบของบัญชีนี้ถูกยกเลิกหรือเปลี่ยนแปลง กรุณาเข้าสู่ระบบใหม่",
                          "DEBT-AUTH-407", extensions={"reason": "account_withdrawn"})
```

(b) replace `OPEN_PREFIX = "/v1/auth/"` (line 352) with

```python
# Exactly the routes that must answer WITHOUT a session. Was the prefix "/v1/auth/";
# Feedback Round 1 / WP10 put the user list and the profile under /v1/auth/ too, and
# those must never be reachable without one.
OPEN_PATHS = ("/v1/auth/config", "/v1/auth/password", "/v1/auth/google", "/v1/auth/me", "/v1/auth/logout")
```

(c) replace

```python
    def __init__(self, app, request_id=lambda: "unknown", roster=lambda: []):
        self.app = app
        self.request_id = request_id
        self.roster = roster
```

with

```python
    def __init__(self, app, request_id=lambda: "unknown", roster=lambda: [],
                 still_allowed=lambda session: True):
        self.app = app
        self.request_id = request_id
        self.roster = roster
        # WP10: asked on every request, so a disabled person's cookie stops working.
        self.still_allowed = still_allowed
```

(d) replace `                or path.startswith(OPEN_PREFIX) or scope.get("method") == "OPTIONS"):` with

```python
                or path in OPEN_PATHS or scope.get("method") == "OPTIONS"):
```

(e) replace

```python
        if session is None:
            response = auth_required().response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return
```

with

```python
        if session is None:
            response = auth_required().response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return
        try:
            allowed = self.still_allowed(session)
        except errors.Problem as problem:           # a configured user list that does not answer
            response = problem.response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return
        if not allowed:
            response = session_withdrawn().response(instance="urn:request:" + self.request_id())
            response.headers["set-cookie"] = cookie_header("", config, 0)
            await response(scope, receive, send)
            return
```

- [ ] **Step 5: `backend/app/routers/login.py`**

(a) replace the first docstring line `"""/v1/auth/* — the only /v1 routes the login middleware lets through without a session.` with

```python
"""/v1/auth/* — sign-in, the session, and (Feedback Round 1 / WP10) the user list.

Only auth.OPEN_PATHS answer without a session; the user list and the profile do not.
```

(b) replace

```python
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from .. import auth
```

with

```python
from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from .. import auth, db, officers, user_accounts
from .today import who
```

(c) in `google_login`, replace

```python
    entry = config.allowlist.get(email)
    if entry is None:
        raise auth.not_on_allow_list(email)
```

with

```python
    # WP10 (F13): the managed rows are merged over the env seed on EVERY sign-in, read
    # fresh — an invitation made a moment ago on another instance counts, and a
    # disabled row wins over the seed.
    entry, state = user_accounts.allow_entry(email, config.allowlist, fresh=True)
    if state == "DISABLED":
        raise auth.account_disabled()
    if entry is None:
        raise auth.not_on_allow_list(email)
```

(d) in `me`, replace

```python
    if session is None:
        raise auth.auth_required()
    return auth.me_payload(session)
```

with

```python
    if session is None:
        raise auth.auth_required()
    # WP10: /me is open (the gate calls it before anything else), so it must end a
    # withdrawn session itself, or a disabled person would see the app for one render.
    if not user_accounts.session_allowed(session, config.allowlist):
        raise auth.session_withdrawn()
    return auth.me_payload(session)
```

(e) append to the end of the file:

```python


# --- WP10: the user list ------------------------------------------------------------------
# None of these is in auth.OPEN_PATHS, so the middleware has already refused a request
# with no session, ended a withdrawn one, and rewritten X-Volt-Officer and a POST's `by`
# from the session. With login off there is no Google sign-in for the list to govern.

def _session(request):
    if not auth.current_config().on:
        raise auth.auth_off()
    session = request.scope.get("volt_auth")
    if session is None:
        raise auth.auth_required()
    return session


def _admin(request):
    session = _session(request)
    if session.get("can_switch"):
        raise user_accounts.identity_not_fixed()
    if session.get("role") not in user_accounts.ADMIN_ROLES:
        raise user_accounts.admin_only()
    return session


@router.get("/v1/auth/users")
def list_users(request: Request):
    session = _admin(request)
    rank = user_accounts.RANK[session["role"]]
    return {"users": user_accounts.listed(auth.current_config().allowlist, session["sub"]),
            "grantable_roles": [r for r in auth.ROLES if user_accounts.RANK[r] <= rank],
            "durable": db.configured(),
            "note_th": None if db.configured() else user_accounts.NOT_DURABLE_TH}


@router.post("/v1/auth/users", status_code=201)
def invite_user(request: Request, body: dict = Body(default={}), x_volt_officer: str = Header(default=None)):
    session = _admin(request)
    user = user_accounts.invite(auth.current_config().allowlist, body or {}, who(body or {}, x_volt_officer),
                                session["role"], {row["uid"] for row in officers.registry()})
    return {"user": user}


@router.post("/v1/auth/users/{uid}:disable")
def disable_user(uid: str, request: Request, body: dict = Body(default={}),
                 x_volt_officer: str = Header(default=None)):
    session = _admin(request)
    user = user_accounts.disable(auth.current_config().allowlist, uid, who(body or {}, x_volt_officer),
                                 session["role"], session["sub"])
    return {"user": user}
```

The role comes from the session, never from `X-Volt-Role`: for a locked session the middleware rewrote that header to the same value, and a switching session is refused before the role is read.

- [ ] **Step 6: `backend/app/main.py`**

(a) in `_lifespan`, replace

```python
        snapshot = odoo_client.cached_snapshot()
        if snapshot:
            orders_domain.set_odoo_rows(snapshot["orders"], snapshot["source"])
    yield
```

with

```python
        snapshot = odoo_client.cached_snapshot()
        if snapshot:
            orders_domain.set_odoo_rows(snapshot["orders"], snapshot["source"])
    # WP10 (F13): the start-up merge of records.user_account over AUTH_ALLOWLIST. A
    # database that does not answer at boot is not fatal here — every sign-in and
    # every session check reads the rows again and refuses 503 until it answers.
    from . import auth as _auth, errors as _errors, user_accounts as _accounts
    if _auth.current_config().on:
        try:
            _accounts.refresh()
        except _errors.Problem:
            pass
    yield
```

(b) replace

```python
from . import auth  # noqa: E402
from . import officers as _officers  # noqa: E402

auth.set_config(auth.load_config())
if auth.current_config().on:
    auth.check_officers(auth.current_config(), _officers.registry())
app.add_middleware(auth.AuthMiddleware,
                   request_id=lambda: REQUEST_ID.get(),
                   roster=lambda: _officers.registry())
```

with

```python
from . import auth  # noqa: E402
from . import officers as _officers  # noqa: E402
from . import user_accounts as _user_accounts  # noqa: E402

auth.set_config(auth.load_config())
if auth.current_config().on:
    auth.check_officers(auth.current_config(), _officers.registry())
app.add_middleware(auth.AuthMiddleware,
                   request_id=lambda: REQUEST_ID.get(),
                   roster=lambda: _officers.registry(),
                   # WP10 (F13): a disabled, dropped or re-invited Google account's cookie stops here.
                   still_allowed=lambda session: _user_accounts.session_allowed(
                       session, auth.current_config().allowlist))
```

- [ ] **Step 7: Run the focused and the pinned login tests**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_auth_users.py tests/test_user_accounts.py tests/test_auth_http.py tests/test_auth_core.py tests/test_audit_coverage.py`
Expected: **74 passed** (11 + 15 + 25 + 19 + 4, measured).

- [ ] **Step 8: Suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; backend = baseline + 11; e2e 31/31 (login is off there). Paste.

- [ ] **Step 9: Commit** (W):

```
feat(auth): invite and disable Google users, merge them at every sign-in, and end a withdrawn session

B10b (Feedback Round 1 / WP10, design F13). GET/POST /v1/auth/users and
POST /v1/auth/users/{uid}:disable for a fixed Manager or Owner; auth_off with login off.
The middleware now opens five exact paths instead of the /v1/auth/ prefix, and asks
the user list on every request, so a disabled or re-roled person's cookie stops within
30 s everywhere and at once on the instance that made the change.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add backend/tests/test_auth_users.py && git commit -F /tmp/…/b10b.txt -- backend/app/auth.py backend/app/routers/login.py backend/app/main.py backend/tests/test_auth_users.py`

---

### Task B12a: `display_name` on `/v1/auth/me`, and `PUT /v1/auth/me/profile`

**Files:**
- Modify: `backend/app/routers/login.py` — `_signed_in` (`:22-26` at b5bdc7c, moved by B10b's import lines), the `me` return, the section comment, one route appended
- Create: `backend/tests/test_auth_display_name.py`

**Interfaces:**
- Consumes: B10a's `display_name_for`, `set_profile`; B10b's `_session`.
- Produces:
  - `GET /v1/auth/me`, `POST /v1/auth/password` and `POST /v1/auth/google` answers gain `display_name` (str), `display_name_source` (`"PROFILE"|"EMAIL"|"USERNAME"`) and `display_name_fallback` (str). `auth.me_payload` itself is unchanged (pinned by `test_auth_core.py:159-166`).
  - `PUT /v1/auth/me/profile` body `{"display_name": str|""|null}` → 200, the same body as `/me`. Any other key → 422 `not_editable`. A bad name → 422 `display_name_invalid`. Login off → 404 `auth_off`. No session → 401 `auth_required`. A switching test account may name itself. Audited `PROFILE_SET`.
  - B11 consumes the route and the three fields; B12b consumes `display_name`.

**Pins:** 0 (`test_auth_core.py:159-166` asserts `me_payload` keys; the new test asserts `display_name` is not in `me_payload`). Density: not a screen.

- [ ] **Step 1 (W):** `git log --oneline -3`.

- [ ] **Step 2: Write the failing test** — create `backend/tests/test_auth_display_name.py`:

```python
"""B12a (Feedback Round 1 / WP11, design F14): /v1/auth/me and the sign-in answer carry
display_name — the person's own, else the e-mail's user part, else the username — and a
signed-in person sets their own from PUT /v1/auth/me/profile."""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth, user_accounts
from app.main import app

SECRET = "s" * 40
FAST = 1000


@pytest.fixture
def on(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true",
               "AUTH_TEST_ACCOUNTS": json.dumps({
                   "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
                   "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER",
                                    "officer": "settasak"}}),
               "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
               "AUTH_ALLOWLIST": json.dumps({"somchai.t@example.co.th": {"role": "OFFICER", "officer": "thip"}})}
    user_accounts.reset()
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _google(monkeypatch):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "Somchai.T@example.co.th", "email_verified": True})
    client = TestClient(app)
    return client, client.post("/v1/auth/google", json={"credential": "tok"})


def test_with_login_off_the_profile_answers_auth_off():
    user_accounts.reset()
    assert TestClient(app).put("/v1/auth/me/profile", json={"display_name": "x"}).json()["code"] == "auth_off"


def test_the_profile_needs_a_session(on):
    r = TestClient(app).put("/v1/auth/me/profile", json={"display_name": "x"})
    assert r.status_code == 401 and r.json()["code"] == "auth_required"


def test_a_google_person_with_no_name_set_is_greeted_by_the_e_mail_user_part(on, monkeypatch):
    client, signed = _google(monkeypatch)
    assert signed.json()["display_name"] == "somchai.t" and signed.json()["display_name_source"] == "EMAIL"
    me = client.get("/v1/auth/me").json()
    assert (me["display_name"], me["display_name_fallback"]) == ("somchai.t", "somchai.t")


def test_a_test_account_with_no_name_set_is_greeted_by_its_username(on):
    client = TestClient(app)
    signed = client.post("/v1/auth/password", json={"username": "manager.test", "password": "manager-pw"})
    assert signed.json()["display_name"] == "manager.test"


def test_a_person_names_themself_and_me_serves_it(on, monkeypatch):
    client, _signed = _google(monkeypatch)
    r = client.put("/v1/auth/me/profile", json={"display_name": "สมชาย"})
    assert r.status_code == 200 and r.json()["display_name"] == "สมชาย" and r.json()["subject"] == "somchai.t@example.co.th"
    me = client.get("/v1/auth/me").json()
    assert (me["display_name"], me["display_name_source"], me["display_name_fallback"]) == ("สมชาย", "PROFILE", "somchai.t")
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["detail"]) == ("PROFILE_SET", {"display_name": "set"})
    cleared = client.put("/v1/auth/me/profile", json={"display_name": ""})
    assert cleared.json()["display_name"] == "somchai.t"


def test_a_switching_test_account_may_name_itself_too(on):
    client = TestClient(app)
    client.post("/v1/auth/password", json={"username": "tester", "password": "tester-pw"})
    assert client.put("/v1/auth/me/profile", json={"display_name": "Somchai"}).json()["display_name"] == "Somchai"


def test_a_bad_name_and_a_key_that_is_not_the_name_are_refused(on, monkeypatch):
    client, _signed = _google(monkeypatch)
    r = client.put("/v1/auth/me/profile", json={"display_name": "x" * 61})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "display_name_invalid"
    r = client.put("/v1/auth/me/profile", json={"display_name": "x", "role": "OWNER"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_editable"
    assert client.get("/v1/auth/me").json()["role"] == "OFFICER"


def test_the_login_core_me_payload_is_unchanged():
    """me_payload (pinned by test_auth_core) stays the session's own fields; the name is
    added by the route, which is the only place that reads the user list."""
    session = auth.new_session("a@example.co.th", "GOOGLE", "OFFICER", "thip", False, now=0)
    assert "display_name" not in auth.me_payload(session)
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_auth_display_name.py`
Expected: **6 failed, 2 passed** (measured on the B10b stage). The failures are `KeyError: 'display_name'` and 404 `not_found` on the PUT. The two that pass are `test_the_profile_needs_a_session`, where the middleware refuses before routing, and `test_the_login_core_me_payload_is_unchanged`.

- [ ] **Step 4: Implement** — in `backend/app/routers/login.py`:

(a) replace

```python
def _signed_in(session, config):
    response = JSONResponse(auth.me_payload(session))
```

with

```python
def _me(session):
    """GET /v1/auth/me's body. WP11: display_name is the person's own, else the e-mail's
    user part, else the username (user_accounts.display_name_for)."""
    return dict(auth.me_payload(session), **user_accounts.display_name_for(session))


def _signed_in(session, config):
    response = JSONResponse(_me(session))
```

(b) in `me`, replace the last line `    return auth.me_payload(session)` with `    return _me(session)`.

(c) replace the comment line `# --- WP10: the user list ------------------------------------------------------------------` with `# --- WP10: the user list and one's own name ---------------------------------------------------`.

(d) append to the end of the file:

```python


@router.put("/v1/auth/me/profile")
def set_my_profile(request: Request, body: dict = Body(default={})):
    session = _session(request)
    user_accounts.set_profile(session, body or {})
    return _me(session)
```

- [ ] **Step 5: Run the focused and the login tests**

Run: `cd backend && VOLT_TEST_PG_URL=…/<task-db>… .venv/bin/python -m pytest tests/test_auth_display_name.py tests/test_auth_users.py tests/test_user_accounts.py tests/test_auth_http.py tests/test_auth_core.py tests/test_auth_schema.py tests/test_audit_coverage.py`
Expected: **83 passed** (8 + 11 + 15 + 25 + 19 + 1 + 4, measured).

- [ ] **Step 6: Suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; backend = baseline + 8. Paste.

- [ ] **Step 7: Commit** (W):

```
feat(auth): /v1/auth/me serves the display name, its source and its fallback; a person names themself

B12a (Feedback Round 1 / WP11, design F14). The name is the person's own, else the
e-mail's user part, else the username. PUT /v1/auth/me/profile sets or clears it and
refuses any other key; audited PROFILE_SET with "set"/"cleared", never the name.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add backend/tests/test_auth_display_name.py && git commit -F /tmp/…/b12a.txt -- backend/app/routers/login.py backend/tests/test_auth_display_name.py`

---
### Task B11: the ผู้ใช้ tab, and the display name in the identity menu

**Files:**
- Modify: `frontend/src/screens/Settings.jsx` — one import (after B9's `fmtWhen` import), one state line after `const [note, setNote] = useState(null)` (`:52`), the tablist + panel wrapper around the four sections (`:193-197` and `:560-562` at b5bdc7c, before B9 — re-find by the strings quoted below)
- Create: `frontend/src/components/UsersPanel.jsx`
- Modify: `frontend/src/components/RoleSwitcher.jsx` — imports `:7`, the session block `:159-164`, one component appended
- Modify: `frontend/src/api.js` — 4 bindings after `authLogout` `:353`
- Modify: `frontend/src/i18n-admin.js` — 23 keys after `'set.title'` (EN `:237`, TH `:802` plus B9's 41)
- Modify: `frontend/src/i18n-journey.js` — 4 keys after `'auth.retry'` (EN `:418`, TH `:852`)
- Modify: `frontend/src/admin.css` (append), `frontend/src/app.css` (after `:459`)
- Create: `frontend/src/screens/Settings.users.test.jsx`, `frontend/src/components/IdentityMenu.name.test.jsx`

**Interfaces:**
- Consumes: B10b's `GET /v1/auth/users` (`users`, `grantable_roles`, `durable`, `note_th`), `POST /v1/auth/users`, `POST /v1/auth/users/{uid}:disable`; B12a's `PUT /v1/auth/me/profile` and the `display_name`, `display_name_source`, `display_name_fallback` fields; `useRoster`, `identitiesForRole` (`role.jsx:145-156`); `setSession` / `useSession` (`auth.jsx`); `fmtWhen`; `role.<ROLE>` and `a11y.tableIn` keys (i18n-journey.js).
- Produces:
  - `api.authUsers()`, `api.authInviteUser({email, role, officer})`, `api.authDisableUser(uid)` (the uid is URI-encoded), `api.authSetProfile({display_name})`.
  - `UsersPanel` (named export). Test ids: `users-panel`, `users-table`, `user-<uid>` (with `data-state`), `user-seeded-<uid>`, `user-by-<uid>`, `user-disable-<uid>`, `user-disable-confirm-<uid>`, `user-problem-<uid>`, `user-invite`, `user-invite-email`, `user-invite-role`, `user-invite-officer`, `user-invite-submit`, `users-auth-off`, `users-not-durable`.
  - Settings tabs (Manager and Owner only): `set-tab-config`, `set-tab-users`; panels `#set-panel-config` (always rendered, `hidden` when not chosen) and `#set-panel-users` (mounted only when chosen, so the list is fetched only then).
  - `ProfileName` (named export from `RoleSwitcher.jsx`). Test ids: `identity-name`, `identity-name-input`, `identity-name-save`.
  - i18n (admin): `set.tabs`, `set.tab.users`, `set.users.{title,note,authOff,email,role,officer,state,stateActive,stateDisabled,seeded,fromSeed,invitedBy{by}{at},disabledBy{by}{at},you,disable,disableConfirm,disabled{email},invite,invited{email},pick}`. i18n (journey): `auth.profile.{label,hint{fallback},save,saved}`.

**Pins:** `Settings.test.jsx` 16/16 and `IdentityMenu.session.test.jsx` 3/3 pass after this task (measured): **0 edits**. The identity panel mounts only while open (`Popover.jsx`: `{open && …}`), so the shell chrome does not grow. Density: Settings has no census; Today untouched.

- [ ] **Step 1 (W):** `git log --oneline -3`. Grep the new keys, expect no output:
`grep -n "'set\.tab\|'set\.users\.\|'auth\.profile\." frontend/src/i18n-*.js frontend/src/prefs.jsx`

- [ ] **Step 2: Write the failing tests** — create `frontend/src/screens/Settings.users.test.jsx`:

```jsx
// B11 (Feedback Round 1 / WP10, design F13): the ผู้ใช้ tab — the managed allow-list.
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderIn } from '../test-utils.jsx'

const { mocks } = vi.hoisted(() => ({ mocks: {} }))
vi.mock('../api.js', () => ({
  api: {
    config: () => Promise.resolve({ config: {}, pending: {} }),
    dictionaries: () => Promise.resolve({ dictionaries: {}, history: [] }),
    bandSets: () => Promise.resolve({ active: 'OPERATIONAL', band_sets: [] }),
    authUsers: () => mocks.authUsers(),
    authInviteUser: (payload) => mocks.authInviteUser(payload),
    authDisableUser: (uid) => mocks.authDisableUser(uid),
  },
}))

import Settings from './Settings.jsx'
import { setRoster } from '../components/role.jsx'

const LIST = {
  users: [
    { uid: 'env-1a2b3c4d5e6f7a8b', email: 'boss@example.co.th', role: 'OWNER', officer: 'owner', display_name: null,
      state: 'ACTIVE', seeded: true, invited_by: null, invited_at: null, disabled_by: null, disabled_at: null, self: false },
    { uid: '4', email: 'lead@example.co.th', role: 'MANAGER', officer: 'settasak', display_name: 'สมชาย',
      state: 'ACTIVE', seeded: false, invited_by: 'owner', invited_at: '2026-09-15T02:00:00+00:00', disabled_by: null, disabled_at: null, self: true },
    { uid: '5', email: 'thip@example.co.th', role: 'OFFICER', officer: 'thip', display_name: null,
      state: 'ACTIVE', seeded: true, invited_by: null, invited_at: null, disabled_by: null, disabled_at: null, self: false },
    { uid: '6', email: 'old@example.co.th', role: 'OFFICER', officer: 'nantapol', display_name: null,
      state: 'DISABLED', seeded: false, invited_by: 'settasak', invited_at: '2026-09-01T02:00:00+00:00',
      disabled_by: 'settasak', disabled_at: '2026-09-10T02:00:00+00:00', self: false },
  ],
  grantable_roles: ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OPS'],
  durable: true, note_th: null,
}

beforeEach(() => {
  window.localStorage.clear()
  setRoster([{ uid: 'nantapol', display_name_th: 'nantapol', role: 'OFFICER' },
             { uid: 'thip', display_name_th: 'ทิพย์อักษร', role: 'OFFICER' }])
  mocks.authUsers = vi.fn(() => Promise.resolve(LIST))
  mocks.authInviteUser = vi.fn(() => Promise.resolve({ user: { email: 'new@example.co.th' } }))
  mocks.authDisableUser = vi.fn(() => Promise.resolve({ user: {} }))
})

async function openUsers(role = 'MANAGER', lang = 'th') {
  window.localStorage.setItem('volt.role', role)
  renderIn(lang, <Settings />)
  fireEvent.click(await screen.findByTestId('set-tab-users'))
  return screen.findByTestId('users-panel')
}

describe('Settings — ผู้ใช้ tab (B11)', () => {
  it('an officer sees no tabs, and nobody fetches the list until the tab is opened', async () => {
    renderIn('th', <Settings />)
    await screen.findByText('ค่าตั้งระบบ')
    expect(screen.queryByTestId('set-tab-users')).toBeNull()
    expect(mocks.authUsers).not.toHaveBeenCalled()
  })

  it('lists who may sign in, marks the seed, and names who invited or disabled', async () => {
    const panel = await openUsers()
    expect(mocks.authUsers).toHaveBeenCalledTimes(1)
    expect(within(panel).getByTestId('user-seeded-env-1a2b3c4d5e6f7a8b')).toHaveTextContent('จาก AUTH_ALLOWLIST')
    expect(within(panel).getByTestId('user-by-4')).toHaveTextContent('เชิญโดย owner เมื่อ 15/09/2026')
    expect(within(panel).getByTestId('user-by-6')).toHaveTextContent('ปิดโดย settasak เมื่อ 10/09/2026')
    expect(within(panel).getByTestId('user-5')).toHaveTextContent('ทิพย์อักษร')
    expect(screen.getByTestId('set-tab-users')).toHaveAttribute('aria-selected', 'true')
  })

  it('offers disable only where the server would allow it: not an Owner above a Manager, not yourself, not a disabled row', async () => {
    const panel = await openUsers()
    expect(within(panel).queryByTestId('user-disable-env-1a2b3c4d5e6f7a8b')).toBeNull()
    expect(within(panel).queryByTestId('user-disable-4')).toBeNull()
    expect(within(panel).getByTestId('user-4')).toHaveTextContent('คุณ')
    expect(within(panel).queryByTestId('user-disable-6')).toBeNull()
    expect(within(panel).getByTestId('user-disable-5')).toBeInTheDocument()
  })

  it('disable asks once more, then posts the uid and reloads the list', async () => {
    const panel = await openUsers()
    fireEvent.click(within(panel).getByTestId('user-disable-5'))
    expect(mocks.authDisableUser).not.toHaveBeenCalled()
    fireEvent.click(within(panel).getByTestId('user-disable-confirm-5'))
    await waitFor(() => expect(mocks.authDisableUser).toHaveBeenCalledWith('5'))
    expect(await screen.findByText('ปิดการใช้งาน thip@example.co.th แล้ว')).toBeInTheDocument()
    expect(mocks.authUsers).toHaveBeenCalledTimes(2)
  })

  it('a refused disable renders the server sentence under the row', async () => {
    mocks.authDisableUser = vi.fn(() => Promise.reject(Object.assign(new Error('x'), { status: 409, problem: {
      code: 'cannot_disable_self', message_th: 'ปิดการใช้งานบัญชีของตัวเองไม่ได้', error_id: 'DEBT-AUTH-413' } })))
    const panel = await openUsers()
    fireEvent.click(within(panel).getByTestId('user-disable-5'))
    fireEvent.click(within(panel).getByTestId('user-disable-confirm-5'))
    const row = await screen.findByTestId('user-problem-5')
    expect(row).toHaveTextContent('ปิดการใช้งานบัญชีของตัวเองไม่ได้')
    expect(row).toHaveTextContent('cannot_disable_self')
  })

  it('the invite form offers only the roles the server says this person may grant, and posts all three fields', async () => {
    const panel = await openUsers()
    const form = within(panel).getByTestId('user-invite')
    const roles = [...within(form).getByTestId('user-invite-role').querySelectorAll('option')].map((o) => o.value)
    expect(roles).toEqual(['', 'OFFICER', 'SUPERVISOR', 'MANAGER', 'OPS'])
    fireEvent.change(within(form).getByTestId('user-invite-email'), { target: { value: ' new@example.co.th ' } })
    fireEvent.change(within(form).getByTestId('user-invite-role'), { target: { value: 'OFFICER' } })
    fireEvent.change(within(form).getByTestId('user-invite-officer'), { target: { value: 'thip' } })
    fireEvent.submit(form)
    await waitFor(() => expect(mocks.authInviteUser).toHaveBeenCalledWith({ email: 'new@example.co.th', role: 'OFFICER', officer: 'thip' }))
    expect(await screen.findByText('เชิญ new@example.co.th แล้ว')).toBeInTheDocument()
  })

  it('a refused invitation shows the field-level Thai sentences', async () => {
    mocks.authInviteUser = vi.fn(() => Promise.reject(Object.assign(new Error('x'), { status: 422, problem: {
      code: 'validation_failed', message_th: 'ข้อมูลไม่ถูกต้อง', error_id: 'DEBT-PLT-0422',
      errors: [{ pointer: '/email', code: 'email_invalid', message_th: 'อีเมลไม่ถูกต้อง' }] } })))
    const panel = await openUsers()
    fireEvent.submit(within(panel).getByTestId('user-invite'))
    expect(await within(panel).findByText(/อีเมลไม่ถูกต้อง/)).toBeInTheDocument()
  })

  it('with login off the tab says so in words and offers no form', async () => {
    mocks.authUsers = vi.fn(() => Promise.reject(Object.assign(new Error('x'), { status: 404, problem: {
      code: 'auth_off', message_th: 'ระบบนี้ไม่ได้เปิดใช้การเข้าสู่ระบบ' } })))
    const panel = await openUsers('OWNER')
    expect(await within(panel).findByTestId('users-auth-off')).toHaveTextContent('ไม่ได้เปิดการเข้าสู่ระบบ')
    expect(within(panel).queryByTestId('user-invite')).toBeNull()
  })

  it('an in-memory list is labelled not durable', async () => {
    mocks.authUsers = vi.fn(() => Promise.resolve({ ...LIST, durable: false, note_th: 'ไม่มีฐานข้อมูล — รายชื่อนี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท' }))
    const panel = await openUsers()
    expect(within(panel).getByTestId('users-not-durable')).toHaveTextContent('หายเมื่อรีสตาร์ท')
  })
})
```

and `frontend/src/components/IdentityMenu.name.test.jsx`:

```jsx
// B11 (Feedback Round 1 / WP10, design F14): a signed-in person sets their own display
// name from the identity menu; the session store takes the server's answer.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'

vi.mock('../api.js', () => ({
  api: {
    officers: vi.fn(() => Promise.resolve({ officers: [] })),
    authLogout: vi.fn(() => Promise.resolve({ signed_out: true })),
    authSetProfile: vi.fn(),
  },
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))

import { api } from '../api.js'
import { IdentityMenu } from './RoleSwitcher.jsx'
import { setSession, readSession } from './auth.jsx'
import { setRole, setOfficer } from './role.jsx'

const GOOGLE = { subject: 'somchai.t@example.co.th', kind: 'GOOGLE', role: 'OFFICER', officer: 'thip', can_switch: false,
                 display_name: 'somchai.t', display_name_source: 'EMAIL', display_name_fallback: 'somchai.t' }

beforeEach(() => {
  window.localStorage.clear()
  setSession(null); setRole('OFFICER'); setOfficer('nantapol')
  api.authSetProfile.mockReset()
})

describe('IdentityMenu — own display name (B11)', () => {
  it('no session: no name field', () => {
    renderIn('en', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    expect(screen.queryByTestId('identity-name')).toBeNull()
  })

  it('a fallback name leaves the field empty and names the fallback in the hint', () => {
    setSession(GOOGLE)
    renderIn('th', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    expect(screen.getByTestId('identity-name-input')).toHaveValue('')
    expect(screen.getByText('เว้นว่างไว้เพื่อให้ระบบเรียกคุณว่า somchai.t')).toBeInTheDocument()
  })

  it('saving puts the SERVED answer into the session, which the greeting reads', async () => {
    setSession(GOOGLE)
    api.authSetProfile.mockResolvedValue({ ...GOOGLE, display_name: 'สมชาย', display_name_source: 'PROFILE' })
    renderIn('en', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    fireEvent.change(screen.getByTestId('identity-name-input'), { target: { value: ' สมชาย ' } })
    fireEvent.click(screen.getByTestId('identity-name-save'))
    await waitFor(() => expect(api.authSetProfile).toHaveBeenCalledWith({ display_name: ' สมชาย ' }))
    await waitFor(() => expect(readSession().display_name).toBe('สมชาย'))
    expect(await screen.findByText('Name saved')).toBeInTheDocument()
  })

  it('a refusal is shown in place and the session keeps its name', async () => {
    setSession(GOOGLE)
    api.authSetProfile.mockRejectedValue(Object.assign(new Error('x'), { status: 422, problem: {
      code: 'validation_failed', message_th: 'ข้อมูลไม่ถูกต้อง',
      errors: [{ pointer: '/display_name', code: 'display_name_invalid', message_th: 'ชื่อที่แสดงยาวได้ไม่เกิน 60 ตัวอักษร และห้ามมีอักขระควบคุม' }] } }))
    renderIn('th', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    fireEvent.click(screen.getByTestId('identity-name-save'))
    expect(await screen.findByText(/ชื่อที่แสดงยาวได้ไม่เกิน 60 ตัวอักษร/)).toBeInTheDocument()
    expect(readSession().display_name).toBe('somchai.t')
  })
})
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/screens/Settings.users.test.jsx src/components/IdentityMenu.name.test.jsx`
Expected: FAIL — `Unable to find an element by: [data-testid="set-tab-users"]` (8 of the 9 Settings.users tests; the officer test passes). In the identity-menu file, 3 of 4 fail on `[data-testid="identity-name-input"]` / `identity-name-save`; the no-session test passes.

- [ ] **Step 4: The API bindings** — in `frontend/src/api.js`, directly after `  authLogout: () => post('/v1/auth/logout', {}),` (line 353):

```js
  // Feedback Round 1 / WP10–WP11: the managed allow-list, and one's own display name.
  authUsers: () => get('/v1/auth/users'),
  authInviteUser: (payload) => post('/v1/auth/users', payload),
  authDisableUser: (uid) => post(`/v1/auth/users/${encodeURIComponent(uid)}:disable`, {}),
  authSetProfile: (payload) => put('/v1/auth/me/profile', payload),
```

- [ ] **Step 5: The panel** — create `frontend/src/components/UsersPanel.jsx`:

```jsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../prefs.jsx'
import { useRoster, identitiesForRole } from './role.jsx'
import { LiveNotice } from './Notice.jsx'
import { Problem } from './Problem.jsx'
import { fromError } from '../problem.js'
import { fmtWhen } from './CaseContactDrawer.jsx'

// B11 (Feedback Round 1 / WP10, design F13): the ผู้ใช้ tab on Settings. The server
// decides everything here — who is on the list, which roles this person may hand out
// (`grantable_roles`), and every refusal. The screen hides a disable button the server
// would refuse (a role you may not grant, yourself, a row already disabled) so nobody
// presses into a refusal, and still renders the refusal in place if one comes. A seed
// entry (AUTH_ALLOWLIST) says so and has no delete anywhere: it can only be disabled,
// and a disabled row comes back by being invited again. With login off the list
// answers auth_off and the tab says that in words, with no form.
export function UsersPanel() {
  const t = useT()
  const roster = useRoster()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [form, setForm] = useState({ email: '', role: '', officer: '' })
  const [formProblem, setFormProblem] = useState(null)
  const [rowProblem, setRowProblem] = useState({ uid: null, problem: null })
  const [confirming, setConfirming] = useState(null)
  const [note, setNote] = useState(null)
  const alive = useRef(true)

  const load = useCallback(() => Promise.resolve()
    .then(() => api.authUsers())
    .then((served) => { if (alive.current) { setData(served); setProblem(null) } })
    .catch((error) => { if (alive.current) { setData(null); setProblem(fromError(error)) } }), [])

  useEffect(() => {
    alive.current = true
    load()
    return () => { alive.current = false }
  }, [load])

  async function invite(event) {
    event.preventDefault()
    setFormProblem(null)
    try {
      const served = await api.authInviteUser({ email: form.email.trim(), role: form.role, officer: form.officer })
      if (!alive.current) return
      setNote(t('set.users.invited', { email: served?.user?.email || form.email.trim() }))
      setForm({ email: '', role: '', officer: '' })
      load()
    } catch (error) {
      if (alive.current) setFormProblem(fromError(error))
    }
  }

  async function disable(user) {
    setRowProblem({ uid: null, problem: null })
    try {
      await api.authDisableUser(user.uid)
      if (!alive.current) return
      setConfirming(null)
      setNote(t('set.users.disabled', { email: user.email }))
      load()
    } catch (error) {
      if (alive.current) { setConfirming(null); setRowProblem({ uid: user.uid, problem: fromError(error) }) }
    }
  }

  if (data === null && problem === null) return <p className="empty">{t('common.loading')}</p>
  if (problem && problem.code === 'auth_off') {
    return (
      <section className="card ad-section" aria-labelledby="set-users" data-testid="users-panel">
        <h2 className="ad-h2" id="set-users">{t('set.users.title')}</h2>
        <p className="ad-quiet" data-testid="users-auth-off">{t('set.users.authOff')}</p>
      </section>
    )
  }

  const users = data?.users || []
  const grantable = data?.grantable_roles || []
  const officers = roster.length > 0 ? roster : identitiesForRole('OFFICER', [])
  const officerName = (uid) => (roster.find((o) => o.uid === uid) || {}).display_name_th || uid || '—'

  return (
    <section className="card ad-section" aria-labelledby="set-users" data-testid="users-panel">
      <h2 className="ad-h2" id="set-users">{t('set.users.title')}</h2>
      <p className="ad-quiet">{t('set.users.note')}</p>
      {data?.note_th && <p className="ad-quiet" data-testid="users-not-durable">{data.note_th}</p>}
      <LiveNotice tone="info" value={note} onDismiss={() => setNote(null)} />
      <Problem problem={problem} endpoint="GET /v1/auth/users" />
      {data && (
        <div className="ad-scroll" tabIndex={0} role="region"
             aria-label={t('a11y.tableIn', { name: t('set.users.title') })}>
          <table className="table" data-testid="users-table">
            <thead>
              <tr>
                <th>{t('set.users.email')}</th>
                <th>{t('set.users.role')}</th>
                <th>{t('set.users.officer')}</th>
                <th>{t('set.users.state')}</th>
                <th aria-label={t('set.users.disable')} />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const mayDisable = user.state === 'ACTIVE' && !user.self && grantable.includes(user.role)
                return [
                  <tr key={user.uid} data-testid={`user-${user.uid}`} data-state={user.state}>
                    <td className="ad-wrap">
                      {user.email}
                      {user.display_name && <span className="ad-quiet"> · {user.display_name}</span>}
                      {user.seeded && <span className="jy-source" data-testid={`user-seeded-${user.uid}`}> · {t('set.users.seeded')}</span>}
                    </td>
                    <td>{user.role ? t(`role.${user.role}`) : '—'}</td>
                    <td>{officerName(user.officer)}</td>
                    <td className="ad-wrap">
                      {user.state === 'DISABLED'
                        ? <span className="chip chip--held">{t('set.users.stateDisabled')}</span>
                        : <span className="chip chip--current">{t('set.users.stateActive')}</span>}
                      <span className="ad-quiet" data-testid={`user-by-${user.uid}`}> · {user.state === 'DISABLED'
                        ? t('set.users.disabledBy', { by: user.disabled_by || '—', at: fmtWhen(user.disabled_at) })
                        : user.invited_by
                          ? t('set.users.invitedBy', { by: user.invited_by, at: fmtWhen(user.invited_at) })
                          : t('set.users.fromSeed')}</span>
                    </td>
                    <td>
                      {user.self && <span className="ad-quiet">{t('set.users.you')}</span>}
                      {mayDisable && confirming !== user.uid && (
                        <button type="button" className="btn btn--sm" data-testid={`user-disable-${user.uid}`}
                                onClick={() => setConfirming(user.uid)}>
                          {t('set.users.disable')}
                        </button>
                      )}
                      {mayDisable && confirming === user.uid && (
                        <span className="jy-actions">
                          <button type="button" className="btn btn--sm btn--primary" data-testid={`user-disable-confirm-${user.uid}`}
                                  onClick={() => disable(user)}>
                            {t('set.users.disableConfirm')}
                          </button>
                          <button type="button" className="btn btn--sm" onClick={() => setConfirming(null)}>{t('set.cancel')}</button>
                        </span>
                      )}
                    </td>
                  </tr>,
                  rowProblem.uid === user.uid ? (
                    <tr key={`${user.uid}-problem`} className="ad-row--problem" data-testid={`user-problem-${user.uid}`}>
                      <td colSpan={5} className="ad-wrap">
                        <Problem problem={rowProblem.problem} endpoint="POST /v1/auth/users/{uid}:disable" />
                      </td>
                    </tr>
                  ) : null,
                ]
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <form className="ad-form" onSubmit={invite} data-testid="user-invite">
          <label className="ad-field">
            <span>{t('set.users.email')}</span>
            <input className="ad-input ad-input--wide" type="email" required value={form.email}
                   data-testid="user-invite-email" onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label className="ad-field">
            <span>{t('set.users.role')}</span>
            <select className="ad-select" required value={form.role} data-testid="user-invite-role"
                    onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="">{t('set.users.pick')}</option>
              {grantable.map((role) => <option key={role} value={role}>{t(`role.${role}`)}</option>)}
            </select>
          </label>
          <label className="ad-field">
            <span>{t('set.users.officer')}</span>
            <select className="ad-select" required value={form.officer} data-testid="user-invite-officer"
                    onChange={(e) => setForm({ ...form, officer: e.target.value })}>
              <option value="">{t('set.users.pick')}</option>
              {officers.map((o) => <option key={o.uid} value={o.uid}>{o.display_name_th || o.uid}</option>)}
            </select>
          </label>
          <button type="submit" className="btn" data-testid="user-invite-submit">{t('set.users.invite')}</button>
        </form>
      )}
      <Problem problem={formProblem} endpoint="POST /v1/auth/users" />
    </section>
  )
}
```

- [ ] **Step 6: The tabs** — in `frontend/src/screens/Settings.jsx`:

(a) after `import { fmtWhen } from '../components/CaseContactDrawer.jsx'` (added by B9) add

```jsx
import { UsersPanel } from '../components/UsersPanel.jsx'
```

(b) after `  const [note, setNote] = useState(null)` add

```jsx
  // B11: two tabs for a Manager or the Owner — the settings, and ผู้ใช้. Local state, not
  // the URL: this screen renders outside a router in its tests, and a tab is a view.
  const [tab, setTab] = useState('config')
```

(c) replace

```jsx
      </header>

      <LiveNotice tone="info" value={note} onDismiss={() => setNote(null)} />

      {/* --- configuration ------------------------------------------------- */}
```

with

```jsx
      </header>

      {canEdit && (
        <div className="ad-tabs" role="tablist" aria-label={t('set.tabs')} onKeyDown={tablistKeyDown}>
          {[['config', t('set.config')], ['users', t('set.tab.users')]].map(([id, label]) => (
            <button key={id} type="button" role="tab" className="ad-tab" id={`set-tab-${id}`}
                    tabIndex={tab === id ? 0 : -1} aria-selected={tab === id}
                    aria-controls={tab === id ? `set-panel-${id}` : undefined}
                    data-testid={`set-tab-${id}`} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </div>
      )}

      <LiveNotice tone="info" value={note} onDismiss={() => setNote(null)} />

      {/* House rule: the settings panel always renders and `hidden` closes it, so every
          test id on it stays reachable; the users panel mounts only when chosen, so its
          list is fetched only by someone who opened it. */}
      <div className="ad-panel" id="set-panel-config" hidden={tab !== 'config'}
           role={canEdit ? 'tabpanel' : undefined} aria-labelledby={canEdit ? 'set-tab-config' : undefined}>
      {/* --- configuration ------------------------------------------------- */}
```

(d) replace the end of the component

```jsx
      <Problem problem={problem} />
    </div>
  )
}
```

with

```jsx
      </div>

      {canEdit && tab === 'users' && (
        <div className="ad-panel" id="set-panel-users" role="tabpanel" aria-labelledby="set-tab-users">
          <UsersPanel />
        </div>
      )}

      <Problem problem={problem} />
    </div>
  )
}
```

`tablistKeyDown` reads `[role="tab"]` under its own container only, so the dictionaries tablist inside the settings panel is not traversed by this one.

- [ ] **Step 7: The name field** — in `frontend/src/components/RoleSwitcher.jsx`:

(a) after `import { setSession, useSession } from './auth.jsx'` add

```jsx
import { Problem } from './Problem.jsx'
import { fromError } from '../problem.js'
```

(b) replace

```jsx
          <p className="identity__subject">{t('auth.signedInAs', { who: session.subject })}</p>
```

with

```jsx
          <p className="identity__subject">{t('auth.signedInAs', { who: session.subject })}</p>
          <ProfileName session={session} />
```

(c) append to the end of the file:

```jsx

// B11 (Feedback Round 1 / WP10, design F14): a signed-in person names themself. The
// server keeps the name and answers with the whole /v1/auth/me body, and the session
// store takes THAT answer — so the Today greeting reads the saved name, never whatever
// the field happened to hold. The field starts empty unless the served name is the
// person's own (display_name_source PROFILE); the fallback is named in the hint.
export function ProfileName({ session }) {
  const t = useT()
  const own = session.display_name_source === 'PROFILE'
  const [value, setValue] = useState(own ? session.display_name || '' : '')
  const [problem, setProblem] = useState(null)
  const [saved, setSaved] = useState(false)
  async function save(event) {
    event.preventDefault()
    setProblem(null)
    setSaved(false)
    try {
      const me = await api.authSetProfile({ display_name: value })
      setSession({ ...session, ...me })
      setSaved(true)
    } catch (error) {
      setProblem(fromError(error))
    }
  }
  const fallback = session.display_name_fallback || session.subject
  return (
    <form className="identity__name" onSubmit={save} data-testid="identity-name">
      <label className="officer-switch">
        <span className="officer-switch__label">{t('auth.profile.label')}</span>
        <input className="ad-input" value={value} maxLength={60} data-testid="identity-name-input"
               aria-describedby="identity-name-hint"
               onChange={(e) => { setValue(e.target.value); setSaved(false) }} />
      </label>
      <p className="identity__hint" id="identity-name-hint">{t('auth.profile.hint', { fallback })}</p>
      <button type="submit" className="btn btn--sm" data-testid="identity-name-save">{t('auth.profile.save')}</button>
      {saved && <span className="identity__saved" role="status">{t('auth.profile.saved')}</span>}
      <Problem problem={problem} endpoint="PUT /v1/auth/me/profile" />
    </form>
  )
}
```

The `alive` guard is not needed here: `ProfileName` sets state only in a submit handler, and `setSession` is a module store.

- [ ] **Step 8: Strings and styles**

(a) `frontend/src/i18n-admin.js` — directly after `  'set.title': 'Settings',` insert:

```js
  // --- B11 (Feedback Round 1 / WP10): the Users tab ---
  'set.tabs': 'Settings sections',
  'set.tab.users': 'Users',
  'set.users.title': 'Who may sign in with Google',
  'set.users.note': 'Invite by e-mail, with the role and the officer the person signs as. A person from AUTH_ALLOWLIST cannot be removed here, only disabled; invite a disabled person again to bring them back. Test accounts are not on this list.',
  'set.users.authOff': 'Sign-in is off on this service, so there is no Google list to manage.',
  'set.users.email': 'E-mail',
  'set.users.role': 'Role',
  'set.users.officer': 'Signs as',
  'set.users.state': 'State',
  'set.users.stateActive': 'active',
  'set.users.stateDisabled': 'disabled',
  'set.users.seeded': 'from AUTH_ALLOWLIST',
  'set.users.fromSeed': 'set by the system seed',
  'set.users.invitedBy': 'invited by {by} on {at}',
  'set.users.disabledBy': 'disabled by {by} on {at}',
  'set.users.you': 'you',
  'set.users.disable': 'Disable',
  'set.users.disableConfirm': 'Disable and sign them out',
  'set.users.disabled': '{email} disabled',
  'set.users.invite': 'Invite',
  'set.users.invited': '{email} invited',
  'set.users.pick': 'Choose…',
```

and directly after `  'set.title': 'ตั้งค่า',` insert:

```js
  // --- B11 (Feedback Round 1 / WP10): แท็บผู้ใช้ ---
  'set.tabs': 'หมวดการตั้งค่า',
  'set.tab.users': 'ผู้ใช้',
  'set.users.title': 'ผู้มีสิทธิ์เข้าสู่ระบบด้วย Google',
  'set.users.note': 'เชิญด้วยอีเมล พร้อมบทบาทและเจ้าหน้าที่ที่ใช้ลงชื่อ รายชื่อจาก AUTH_ALLOWLIST ลบจากหน้านี้ไม่ได้ ทำได้เพียงปิดการใช้งาน และเชิญอีกครั้งเพื่อเปิดใช้ บัญชีทดสอบไม่อยู่ในรายการนี้',
  'set.users.authOff': 'ระบบนี้ไม่ได้เปิดการเข้าสู่ระบบ จึงไม่มีรายชื่อ Google ให้จัดการ',
  'set.users.email': 'อีเมล',
  'set.users.role': 'บทบาท',
  'set.users.officer': 'ลงชื่อเป็น',
  'set.users.state': 'สถานะ',
  'set.users.stateActive': 'ใช้งานได้',
  'set.users.stateDisabled': 'ปิดการใช้งาน',
  'set.users.seeded': 'จาก AUTH_ALLOWLIST',
  'set.users.fromSeed': 'กำหนดจากค่าตั้งต้นของระบบ',
  'set.users.invitedBy': 'เชิญโดย {by} เมื่อ {at}',
  'set.users.disabledBy': 'ปิดโดย {by} เมื่อ {at}',
  'set.users.you': 'คุณ',
  'set.users.disable': 'ปิดการใช้งาน',
  'set.users.disableConfirm': 'ยืนยันปิดการใช้งานและให้ออกจากระบบ',
  'set.users.disabled': 'ปิดการใช้งาน {email} แล้ว',
  'set.users.invite': 'เชิญ',
  'set.users.invited': 'เชิญ {email} แล้ว',
  'set.users.pick': 'เลือก…',
```

(b) `frontend/src/i18n-journey.js` — directly after `  'auth.retry': 'Try again',` (line 418) insert:

```js
  // B11 (Feedback Round 1 / WP10, design F14): one's own display name, in the identity menu.
  'auth.profile.label': 'Your display name',
  'auth.profile.hint': 'Leave it empty to be greeted as {fallback}',
  'auth.profile.save': 'Save name',
  'auth.profile.saved': 'Name saved',
```

and directly after `  'auth.retry': 'ลองใหม่',` (line 852) insert:

```js
  // B11 (Feedback Round 1 / WP10, design F14): ชื่อที่แสดงของตัวเอง ในเมนูตัวตน
  'auth.profile.label': 'ชื่อที่แสดงของคุณ',
  'auth.profile.hint': 'เว้นว่างไว้เพื่อให้ระบบเรียกคุณว่า {fallback}',
  'auth.profile.save': 'บันทึกชื่อ',
  'auth.profile.saved': 'บันทึกชื่อแล้ว',
```

(c) append to `frontend/src/admin.css`:

```css
/* --- B11 (Feedback Round 1 / WP10): the settings tabs' panels keep the page's 16px rhythm. --- */
.ad-panel { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
```

(d) in `frontend/src/app.css`, directly after `.pop__panel .role-switch__ask { max-width: none; margin-top: 0; }` (line 459):

```css
/* B11 (Feedback Round 1 / WP10): one's own display name, in the identity panel. */
.pop__panel .identity__name { display: flex; flex-direction: column; align-items: stretch; gap: 6px; margin: 0; }
.identity__hint { margin: 0; font: var(--caption-12); color: var(--ink-500); }
.identity__saved { font: var(--caption-12); color: var(--status-current); }
```

- [ ] **Step 9: Run the new tests, the pinned files and parity**

Run: `cd frontend && npx vitest run src/screens/Settings.users.test.jsx src/components/IdentityMenu.name.test.jsx src/components/IdentityMenu.session.test.jsx src/screens/Settings.test.jsx src/screens/Settings.form.test.jsx src/i18n.test.js`
Expected: **9 + 4 + 3 + 16 + 8 + 19 = 59 passed** (measured).

- [ ] **Step 10: Suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; frontend = baseline + 13 tests, + 2 files. Paste.

- [ ] **Step 11: Commit** (W):

```
feat(settings, identity): the Users tab — invite, disable, the seed marked — and one's own display name

B11 (Feedback Round 1 / WP10, design F13/F14). The tab is a Manager's or the Owner's,
fetches only when opened, offers only the roles the server says may be granted, asks
before disabling, and says in words when sign-in is off. The identity menu's name field
stores the server's answer in the session.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

`git add frontend/src/components/UsersPanel.jsx frontend/src/screens/Settings.users.test.jsx frontend/src/components/IdentityMenu.name.test.jsx && git commit -F /tmp/…/b11.txt -- frontend/src/screens/Settings.jsx frontend/src/components/UsersPanel.jsx frontend/src/components/RoleSwitcher.jsx frontend/src/api.js frontend/src/i18n-admin.js frontend/src/i18n-journey.js frontend/src/admin.css frontend/src/app.css frontend/src/screens/Settings.users.test.jsx frontend/src/components/IdentityMenu.name.test.jsx`

---

### Task B12b: Today greets the person — `สวัสดี {name}` and one positive line

**Files:**
- Modify: `frontend/src/screens/Today.jsx` — **the title region only:** import after `:5`; `HELLO_LINES` + `helloLineKey` inserted before `export default function Today()` `:135`; two lines after `const roster = useRoster()` `:172`; the `<h1 className="page-title">{t('today.title')}</h1>` line `:751`; branch B adds one line after `<p className="page-sub" aria-live="polite">` `:754`. Line numbers are at b5bdc7c, **before P1's B1–B3** — re-find every anchor by its string.
- Modify: `frontend/src/i18n-today.js` — 6 keys after `'today.title'` (EN `:151`, TH `:740`)
- Modify: `frontend/src/today.css` — branch A only, append
- Create: `frontend/src/screens/Today.greeting.test.jsx`

**Interfaces:**
- Consumes: `useSession()` → `display_name` (B12a); `useRoster()` rows `{uid, display_name_th}` and `useOfficer().officer` (already `acting` at Today.jsx:145); `data.run.business_date` (already `businessDate`, Today.jsx:417); `isoDay` (NextAction.jsx).
- Produces: exports `HELLO_LINES` (5) and `helloLineKey(businessDate) -> 'today.hello.line.<1..5>'`. The `<h1>` reads `t('today.hello', { name })`, where name is the session's `display_name` when signed in, else the acting identity's roster `display_name_th`, else its uid. The h1 carries `data-testid="today-hello"`; branch A's line is `data-testid="today-hello-line"`. i18n: `today.hello` `{name}`; `today.hello.line.1`–`.5` (no digit in either language, tested).

**Pins:** title text **0** (measured; see the header). Density:
- measured before (at b5bdc7c, before P1): `TODAY chrome=112 perRow=31 at 50 rows=1662`.
- branch A measured: `chrome=113 … at 50 rows=1663`. That exceeds 112 / 1,662, and the controller ruling keeps the caps, so **no numbered edit is spent**.
- branch B measured: `chrome=112 … 1662`. That is the cut.

- [ ] **Step 1 (W): Choose the branch from the census.** `git log --oneline -5`. Confirm P1's B4 commit is on the branch and read its pasted census line (or run it now):
`cd frontend && npx vitest run src/today-density.test.jsx 2>&1 | grep "TODAY  chrome\|TODAY  full"`
- chrome **≤ 111** and full page **≤ 1,661** → **branch A** (the line is its own `<p>`, +1).
- chrome **= 112** or full page **= 1,662**, or P1 has not landed → **branch B** (the line is the first sentence of the sub-line, +0).
Paste the census line and the branch taken into the report.

- [ ] **Step 2 (W):** grep the new keys, expect no output: `grep -n "'today\.hello" frontend/src/i18n-*.js frontend/src/prefs.jsx`

- [ ] **Step 3: Write the failing test** — create `frontend/src/screens/Today.greeting.test.jsx` (the same file serves both branches: it finds the line by text, not by element):

```jsx
// WP11 (design F14, B12): Today greets the person by name, with one positive line
// that rotates by business day and never carries a number.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setOfficer, setRole, setRoster } from '../components/role.jsx'
import { setSession } from '../components/auth.jsx'
import { TODAY_EN, TODAY_TH } from '../i18n-today.js'
import TodayScreen, { helloLineKey, HELLO_LINES } from './Today.jsx'

vi.mock('../api.js', () => ({
  api: {
    today: vi.fn(), todayItemDone: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(),
    dictionary: vi.fn(), logContact: vi.fn(), logCaseContact: vi.fn(), retractContact: vi.fn(),
    uploadAttachment: vi.fn(), addContactNote: vi.fn(),
  },
}))

const RESPONSE = (businessDate = '2026-10-23') => ({
  run: { business_date: businessDate, job: 'today', officer: null, ordering: 'tiers' },
  items: [],
  meta: { total: 0, next_up: null, tiers: [], counts_by_tier: {} },
})

async function mount(lang = 'th', businessDate) {
  api.today.mockResolvedValue(RESPONSE(businessDate))
  api.reminders.mockResolvedValue({ items: [], meta: {} })
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  renderIn(lang, <MemoryRouter initialEntries={['/']}><TodayScreen /></MemoryRouter>)
  return screen.findByRole('heading', { level: 1 })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  setSession(null)
  setRoster([])
  setRole('OFFICER')
  setOfficer('nantapol')
})

describe('Today greeting (B12)', () => {
  it('login off: greets the chosen officer by the roster Thai name', async () => {
    setRoster([{ uid: 'thip', display_name_th: 'ทิพย์อักษร', role: 'OFFICER' },
               { uid: 'nantapol', display_name_th: 'nantapol', role: 'OFFICER' }])
    setOfficer('thip')
    const heading = await mount('th')
    expect(heading).toHaveTextContent('สวัสดี ทิพย์อักษร')
  })

  it('login off with no roster: the acting uid stands in', async () => {
    const heading = await mount('en')
    expect(heading).toHaveTextContent('Hello, nantapol')
  })

  it('login on: the served display_name wins over the roster', async () => {
    setSession({ subject: 'somchai@example.co.th', kind: 'GOOGLE', role: 'OFFICER', officer: 'thip',
                 can_switch: false, display_name: 'สมชาย' })
    const heading = await mount('th')
    expect(heading).toHaveTextContent('สวัสดี สมชาย')
  })

  it('one positive line, chosen by the served business day, never a number', async () => {
    await mount('th', '2026-10-23')
    expect(helloLineKey('2026-10-23')).toBe('today.hello.line.5')
    expect(helloLineKey('2026-10-24')).toBe('today.hello.line.1')
    expect(helloLineKey(undefined)).toBe('today.hello.line.1')
    expect(screen.getByText(TODAY_TH['today.hello.line.5'], { exact: false })).toBeInTheDocument()
    for (let i = 1; i <= HELLO_LINES; i += 1) {
      for (const table of [TODAY_EN, TODAY_TH]) {
        const line = table[`today.hello.line.${i}`]
        expect(line, `today.hello.line.${i}`).toBeTruthy()
        expect(line).not.toMatch(/[0-9๐-๙]/)
      }
    }
  })
})
```

- [ ] **Step 4: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/screens/Today.greeting.test.jsx`
Expected: FAIL — `helloLineKey is not a function`, and the headings read "วันนี้" / "Today".

- [ ] **Step 5: Strings** — `frontend/src/i18n-today.js`, directly after `  'today.title': 'Today',` (line 151):

```js
  // B12b (Feedback Round 1 / WP11): the greeting, and five positive lines — never a number.
  'today.hello': 'Hello, {name}',
  'today.hello.line.1': 'Every call today moves a customer forward.',
  'today.hello.line.2': 'Start with the first name on the list; the rest will follow.',
  'today.hello.line.3': 'A calm, kind word on the phone goes a long way.',
  'today.hello.line.4': 'Thank you for keeping every promise on record.',
  'today.hello.line.5': 'Small steps every day add up to a good month.',
```

and directly after `  'today.title': 'วันนี้',` (line 740):

```js
  // B12b (Feedback Round 1 / WP11): คำทักทาย และข้อความให้กำลังใจห้าข้อ — ไม่มีตัวเลข
  'today.hello': 'สวัสดี {name}',
  'today.hello.line.1': 'ทุกสายที่โทรวันนี้ช่วยให้ลูกค้าก้าวไปข้างหน้า',
  'today.hello.line.2': 'เริ่มจากรายชื่อแรกในรายการ ที่เหลือจะตามมาเอง',
  'today.hello.line.3': 'น้ำเสียงที่ใจเย็นและสุภาพช่วยให้คุยกันง่ายขึ้นเสมอ',
  'today.hello.line.4': 'ขอบคุณที่บันทึกทุกนัดชำระไว้อย่างครบถ้วน',
  'today.hello.line.5': 'ก้าวเล็ก ๆ ทุกวันรวมกันเป็นเดือนที่ดี',
```

`today.title` stays (other screens and the rail use `nav.today`; nothing else reads `today.title` after this, and keeping it costs nothing).

- [ ] **Step 6: Implement (both branches share a–c)** — in `frontend/src/screens/Today.jsx`:

(a) after `import { useRole, useOfficer, useRoster, OFFICERS } from '../components/role.jsx'` add

```jsx
import { useSession } from '../components/auth.jsx'
```

(b) directly above `export default function Today() {` add

```jsx
// WP11 (design F14): five short positive lines, one per business day, never a number.
export const HELLO_LINES = 5
export function helloLineKey(businessDate) {
  const day = isoDay(businessDate)
  const n = day ? Math.floor(Date.parse(`${day}T00:00:00Z`) / 86400000) : 0
  return `today.hello.line.${(n % HELLO_LINES) + 1}`
}

```

(the index is a choice of copy, not a figure the server owns — `api.js:1-4` is about served numbers.)

(c) directly after `  const roster = useRoster()` add

```jsx
  const session = useSession()
  const helloName = (session && session.display_name)
    || (roster.find((o) => o.uid === acting) || {}).display_name_th || acting
```

(d-A) **branch A** — replace `          <h1 className="page-title">{t('today.title')}</h1>` with

```jsx
          <h1 className="page-title" data-testid="today-hello">{t('today.hello', { name: helloName })}</h1>
          <p className="td-hello" data-testid="today-hello-line">{t(helloLineKey(businessDate))}</p>
```

and append to `frontend/src/today.css`:

```css
/* B12b (Feedback Round 1 / WP11): the one positive line under the greeting. */
.td-hello { margin: 0; font: var(--body-14); color: var(--ink-600); }
```

(d-B) **branch B** — replace `          <h1 className="page-title">{t('today.title')}</h1>` with

```jsx
          <h1 className="page-title" data-testid="today-hello">{t('today.hello', { name: helloName })}</h1>
```

and directly after `          <p className="page-sub" aria-live="polite">` insert

```jsx
            {/* B12b (chrome at its cap, 112): the positive line is the sub-line's first
                sentence — a text node, 0 elements. */}
            {t(helloLineKey(businessDate))}{' · '}
```

`today.css` is not touched in branch B.

- [ ] **Step 7: Run the new test and the Today pins**

Run: `cd frontend && npx vitest run src/screens/Today.greeting.test.jsx src/screens/Today.test.jsx src/screens/Today.board.test.jsx src/round4.test.jsx src/i18n.test.js`
Expected: **4 + 32 + 10 + 45 + 19 = 110 passed** (measured with either branch).

- [ ] **Step 8: Measure density after** — `cd frontend && npx vitest run src/today-density.test.jsx 2>&1 | grep "TODAY"`
Expected: branch A → chrome = (Step 1's chrome + 1) ≤ 112, full page = (Step 1's page + 1) ≤ 1,662; branch B → identical to Step 1. 5/5 pass. **Paste both census lines (before, after).** If the after-line exceeds a cap, stop: switch to branch B (never raise the cap).

- [ ] **Step 9: Suite** — `./scripts/verify_all.sh`. Expected: EVERYTHING PASSED; frontend = baseline + 4 tests, + 1 file. Paste.

- [ ] **Step 10: Commit** (W):

```
feat(today): greet the person by name with one positive line that changes by day

B12b (Feedback Round 1 / WP11, design F14). The name is the signed-in person's
display_name, or with login off the chosen officer's Thai name. Branch <A|B> per the
census: chrome <before> → <after>, page <before> → <after>; caps unchanged.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

Branch A: `git add frontend/src/screens/Today.greeting.test.jsx && git commit -F /tmp/…/b12b.txt -- frontend/src/screens/Today.jsx frontend/src/i18n-today.js frontend/src/today.css frontend/src/screens/Today.greeting.test.jsx`
Branch B: the same pathspec without `frontend/src/today.css`.

---

## Self-review (P3)

**Spec coverage, line by line against design §3 WP10 / WP11 and the brief:**

| Design / brief line | Where |
|---|---|
| "Form, not table … grouped into sections with Thai headings: ค่าปรับและผ่อนผัน · การเตือน · NPL · การตัดไฟ · ใบแจ้งหนี้ · ค่าถอด · ช่วงอายุหนี้ · PEAK (locked)" | B9 `CONFIG_GROUPS` + `set.group.*` (plus "other" for an unfiled key; `review_sla_hours` filed under reminders — ruling 12) |
| "label (TH/EN), input with unit" | B9 `set.key.*` (both tables), `set.unit.*`, `ConfigField` |
| "a state badge (รอตัดสิน / ตัดสินแล้ว / ล็อก)" | B9 keeps `StateChip` (the pinned `state-locked`, `.pending-badge`, `state-decided`) |
| "the source line ('Decision log · ruling 87')" | B9 `cfg-source-<key>`, `set.source.ruling` |
| "a lock icon when the caller's role may not edit it" | B9 `LockMark` / `cfg-lock-<key>` (role="img", so the pinned "no button in the row" holds) |
| "แก้ไขล่าสุดโดย … เมื่อ …" + "config store keeps changed_by and changed_at per key" | B8 (store, route, audit) + B9 `cfg-changed-<key>` |
| "Dictionaries, band sets and assignment keep their sections, restyled the same way" | Kept unchanged inside the settings panel; they already use `.card .ad-section` / `.ad-h2`, the same heading style the form's sections now sit beside. **Not restyled further** — say so in review if a visual pass wants more |
| "records.user_account (email \| username, kind, role, officer, display_name, invited_by, invited_at, disabled_at)" | B10a (+ `disabled_by`, `id`) |
| "env AUTH_ALLOWLIST stays as the seed; rows merged over it at start-up and on each Google sign-in; a disabled row wins" | B10a `allow_entry`; B10b `_lifespan` refresh + `google_login` fresh read |
| "Owner and Manager may invite (e-mail + role + officer) and disable; every act is audited" | B10a `invite` / `disable` (`USER_INVITED`, `USER_DISABLED`); B10b routes |
| "Any signed-in person may set their own display name from the identity menu" | B12a route + B11 `ProfileName` |
| "Password test accounts are unchanged" | `load_config` untouched; TEST sessions always pass `session_allowed`; TEST rows carry only a display name; test `test_a_password_test_account_is_untouched_by_the_list` |
| Brief: an invite cannot grant a role above the inviter's | `role_above_actor`; tests in B10a and B10b |
| Brief: a Manager cannot disable an Owner or themselves | `role_above_actor`, `cannot_disable_self`; tests in both |
| Brief: a disabled row refuses sign-in and ends existing sessions | `account_disabled`; middleware + `/me` `session_withdrawn`; ≤ 30 s on other instances (ruling 7) |
| Brief: the env seed cannot be deleted from the UI | no delete route or function (tested); disable + re-invite only |
| Brief: e-mails not logged beyond the audit subject | audit detail carries role/officer/flags only (tested); refusals carry no e-mail (tested); list uids are digests (ruling 8); `IntegrityError` never surfaces its text |
| Brief: `AUTH_MODE` never written to `backend/.env` | tests use environ dicts and `env_file=tmp_path / "none"` |
| Brief: login tests with `AUTH_MODE` off unaffected | middleware returns before the hook when off; routes answer `auth_off`; `test_auth_http.py` 25/25 |
| WP11: `display_name` on `/v1/auth/me` (profile, else e-mail user part, else username) | B12a |
| WP11: "สวัสดี {name}" + one short positive line, rotating from an i18n list, never a number | B12b (`today.hello`, `today.hello.line.1-5`, digit-free test) |
| WP11: with login off, the chosen officer's `display_name_th` | B12b `helloName` from `useRoster` + `acting`; test "login off" |

**Placeholder scan:** every step carries full code or an exact old → new edit, anchored on strings read at b5bdc7c. The only open values are `<task-db>` (the controller assigns it), the message-file path, and B12b's census numbers (read at dispatch). No "TBD", no "add validation", no "similar to Task N".

**Name consistency with what these tasks consume:**
- `who` (today.py:27), `officers.registry()` (officers.py:27), `errors.Problem` signature (errors.py:19), `errors.validation_failed` / `not_found`, `audit.describe` (audit.py:136), `clock.stamp` (clock.py:42), `db.configured` / `connect` / `DatabaseUnreachable`, `migrate.apply`, `session.Store(dict, key=…)` — all read in the code.
- `auth.load_config`, `auth.me_payload`, `auth.cookie_header`, `auth.auth_off`, `auth.auth_required`, `auth.not_on_allow_list`, `auth.ROLES` — read in `auth.py`.
- Frontend: `useRoster`, `identitiesForRole(role, list)`, `setRoster`, `setSession`, `useSession`, `readSession`, `fmtWhen`, `formatDate`, `isoDay`, `tablistKeyDown`, `Problem`, `LiveNotice`, `PendingBadge`, `fromError`, `renderIn` — read in their files.
- B11 consumes exactly B10b's `users`, `grantable_roles`, `durable`, `note_th`, `uid`, `email`, `role`, `officer`, `display_name`, `state`, `seeded`, `invited_by`, `invited_at`, `disabled_by`, `disabled_at`, `self`, and B12a's `display_name`, `display_name_source`, `display_name_fallback`. B12b consumes `display_name`.

**Could not verify in the code (assumptions):**
1. **Runtime grants on staging.** Round A recorded that the `records` schema needs grants from another session's uncommitted `migrate.py` edit. `records.user_account` needs the same grants before B10 works on staging. Not fixed here.
2. **The 30-second window** (ruling 7) assumes staging's `--max-instances 4` (auth.py:237 comment) and that Arina accepts a disabled session lasting ≤ 30 s on another instance.
3. **Pre-existing e-mail exposure outside this cluster.** `main.py:280-282` records `actor_claimed = session["sub"]` — the Google e-mail — on every act by a Google session. `auth.not_on_allow_list` echoes the e-mail in the response `extensions`. Read strictly, the PDPA line "e-mails only in the user-account table and the audit subject" is already not true of the audit log. Neither is changed here; it is flagged for the controller.
4. **Google sign-in was never exercised live.** No client id is configured (memory: login build). Every Google test monkeypatches `verify_google_token`.
5. **P1's final Today header.** B12b's branch depends on B4's census, and branch B's anchor (`<p className="page-sub" aria-live="polite">`) assumes P1 keeps that paragraph. If P1 removes it, B12b stops and asks.
6. **Officer registry drift.** An invitation validates its officer against `officers.registry()` when it is made. A row whose officer later leaves the registry is not re-checked at start-up; the env seed still is, by `check_officers`.
7. **The login design doc** (`docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md`) was not re-read; the code was.
8. **Baseline drift.** The branch moved twice during planning (caddc4b → b5bdc7c → 81d2760, all by another session, none touching these files). Each task pastes the live count; the "+N" deltas are the firm part.


<!-- ===== cluster section: P4-wp12.md ===== -->

## WP12 — Weekly figures the API does not send yet (planner P4: Tasks B13, B14)

**Work package:** design §3 WP12, decision F15 (a), "definitions as in WP12's table".

**Tasks:**
- **B13** serves the five figures from `reports.weekly()`. It is backend only and buildable now.
- **B14** renders them on the weekly overview and writes them into the Excel export. It is **BLOCKED** (see its header).

**Deviation from note 11's B13 row, and why.** Note 11 listed `weekly_export.py` under B13. By the controller's ruling that file is another session's uncommitted work. It is not on this branch, so its cells move to B14.

B13 also puts the computation in a new module, `backend/app/weekly_figures.py`, rather than inline in `reports.py`. The module has one job (the five F15 figures), it is testable without HTTP, and the edit to `reports.py` stays two small hunks. The payload key names are note 11's: `mom`, `paying_customers`, `npl_movement`, `arrears_split`, `status_changes`.

**Shared files**
- **`backend/app/reports.py`** — B13 edits lines 10–11 (import) and 253–255 (the tail of `weekly()`'s return dict). No other cluster is known to edit this file.
- **Hotspot contracts B13 reads but does not edit.** A task in another cluster that changes any of these breaks B13's tests:
  - **`backend/app/cases.py`**
    - the `PAYMENT_STATUS_SET` event keys at `:196-198` and `:1024-1026` (`from`, `code`, `system`, `by`, `reason`, `on`, `ended`)
    - `case["allocation_hold"]` at `:294`, `set_allocation_hold` at `:513`, `case_arrears` at `:503`
    - `log_contact` at `:1090`, `cs.issues` via `_make_issue` at `:852`
    - P2 (B6 `set_phone`) and P5 (C2 notices) also edit this file.
  - **`backend/app/today.py:186`** — `build(officer=None, business_date=None, ladder_indicative=None)` called with no arguments must keep returning every in-collection item. P1's B2 adds Today filters and must keep that default.
  - **`backend/app/routers/journey.py:193-255`** — `_work_item`. B13 reads only `item["customer"]["uid"]`. P2's B6 edits this function.
  - **`backend/app/journey.py`** — `contract_by_uid` `:181`, `customer_by_uid` `:176`, `open_issue_for` `:236`, `make_receipt` `:324`, `make_npl_case` `:418`, and the PEAK receipt `source` at `:994`. Those are the `caddc4b` numbers; at `b5bdc7c` they read `:181`, `:176`, `:245`, `:333`, `:443`, `:1019`.
- **B14 only (blocked):**
  - `frontend/src/i18n-admin.js` (a hotspot; P3's B9 and B11 also edit it)
  - `frontend/src/components/WeeklyOverview.jsx` and `backend/app/weekly_export.py` (neither exists on this branch)

**Depends on**
- **B13:** nothing in another Round B/C cluster. It consumes Round A Task 7 (PEAK receipts with `source == "PEAK_REPORT"`) and Task 11 (`cases._follow` writing a SYSTEM `PAYMENT_STATUS_SET`). Both are committed at `caddc4b`.
- **B14:** B13, plus the external commit named in B14's unblock condition.

### Global constraints (copied from the Rounds B/C brief; every task below carries them)

- **Baseline to beat (at caddc4b):** backend 1,022 passed / 11 skipped, frontend 726 passed / 63 files, e2e 31 of 31 (`scripts/verify_all.sh`).
- **Test contract:** a pinned (pre-existing) test changes only as a numbered edit 36–39. The edit must be measured first. It carries a comment `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`. Adding tests is free. Say in each task which pins it touches, with the file:line and the measured number, or "0".
- **Density ratchets:**
  - `frontend/src/density.test.jsx` caps the case page at 109 pre-contact / 128 worked. Its fixtures carry a served `payment_summary` and a stale `payment_position`.
  - `frontend/src/today-density.test.jsx` caps Today at 31 per row, 112 chrome, 1,662 per 50-row page.
  - Every screen task measures before and after, and pastes the census lines. A task that would exceed a cap either cuts, or spends a numbered edit with the measured number. Say which, in the plan.
  - A density fixture that does not carry the block a task adds does not measure it. The measure step must serve the block in a scratch copy.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns. That includes sums across served rows.
- REQ-COL-075: `payment_status` keeps its five values. `payment_status` and `dc_status` stay two fields. `StatusPair` is not modified.
- PKD-001: `backend/app/integrations/peak.py` keeps exactly four public functions and stays DRAFT_ONLY. C1 adds a NEW module and never imports or edits `peak.py`.
- **Raw-body uploads only.** `python-multipart` is not installed, so an `UploadFile` parameter stops the app booting.
- **Honesty rules:**
  - A configured-but-unreachable dependency refuses; an unconfigured one is labelled.
  - Every refusal is an RFC 9457 problem with `message_th`. In `routers/today.py`, `problem_from(exc)` only fills `errors[0]` when the CaseError carries a `pointer=` extra.
  - Indicative figures are badged. Nothing falls back silently; that includes an unknown query value, which is a 422, not ignored.
- **PDPA:**
  - A phone number is stored only in its `records` table and never logged. Audit detail carries "set"/"cleared", not the number.
  - E-mail addresses appear only in the user-account table and the audit subject.
  - The PEAK 13-digit id is never stored.
  - `AUTH_MODE` is never written into `backend/.env`. Test-account passwords (`~/.volt-test-accounts.json`) are never printed.
- **Every write route is role-gated where the design names a role, and audited** (`audit.describe(act=…, subject=…, detail=…)`) before any side effect that can raise.
  - Sign the acting person with `who(body, x_volt_officer)` from `routers/today.py`.
  - `officers.sign` returns a TUPLE `(by, by_role)`, so never compare it to a string.
- **Strings:** user-facing text goes in `frontend/src/i18n-*.js`. Each file is two FLAT objects (`TODAY_EN`/`TODAY_TH`, `OPS_EN`/`OPS_TH`, `ADMIN_EN`/`ADMIN_TH`, `JOURNEY_EN`/`JOURNEY_TH`), never `prefs.jsx`'s `DICT`. `i18n.test.js` checks parity, `{slots}` and cross-table collisions, but NOT a same-table overwrite. Every new key is grepped across all four tables first, and the plan says so.
- **Python:** 3.9-safe (no `match`, no runtime `X | Y`).
- **CSS:** real tokens only. `tokens.css` has `--ink-*`, `--line-default`, `--caption-12`, `--label-13`, `--body-strong-14`. It has no `--space-*`, `--radius-*` or bare `--line`. Use literal px for spacing and no hex literals.
- **Frontend patterns that bit Round A:**
  - `SearchSelect` must get `className`, `labelClassName` and `triggerClassName`, like Payments.jsx:101-115.
  - Async effects need an unmount/`alive` guard.
  - A vitest `vi.mock('../api.js')` object must return a Promise from every binding the component calls at mount.
  - `rerender` must re-wrap `PrefsProvider` or it remounts.
  - Role in tests: `window.localStorage.setItem('volt.role', …)` or `setRole` from `components/role.jsx`.
  - Today mounts `CaseContactDrawer` with `key={drawerFor.customer.uid}`.
- **Backend patterns:**
  - `/v1/workbook` and both CSV exports share `_workbook(...)`.
  - Server-side sort keys live in its `keyfn` map.
  - The run registry's finished state is `"done"`, with result fields at the top level.
  - `X-Volt-Filename` must be `urllib.parse.unquote`d before sanitising.
- **Worktree rules for implementers (put them in each task):**
  - The backend interpreter is `backend/.venv/bin/python`; run pytest without `-q`.
  - Each task names its own `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<db>?host=/Users/parattakorn/.volt-postgres/data`. The controller assigns the database; write `<task-db>`.
  - Never set `DATABASE_URL` to `volt_local`. Never use a bare `git stash`. Never cd into `/Users/parattakorn/volt-debt-prototype`.
  - Commit with a message FILE plus a pathspec: `git commit -F <file> -- <paths>`. The message ends with the two lines `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W`.
  - Never `git add -A`.

### What was measured before cutting B13 (at `caddc4b`, fixture book, no `DATABASE_URL`)

Scripts and scratch copies are in `/private/tmp/claude-502/-Users-parattakorn-volt-debt-prototype/205a91ba-9da2-4067-9ec8-d2f683e4a721/scratchpad/rounds-bc/P4/`: `measure*.py`, `head/` (B13 applied), and `pristine/`. None of them touches the worktree.

| Question | Measured answer |
|---|---|
| Does `PAYMENT_STATUS_SET` carry from/to/by/reason? | Yes. There are two append sites:<ul><li>`cases.py:196-198`: the system follows the data, `by: "SYSTEM"`, `reason: None`, `ended` = the person's change it ended.</li><li>`cases.py:1024-1026`: a person, with a required reason.</li></ul>Keys: `kind, case_uid, from, code` (the new value), `system, by, reason, on, ended`. There is **no `by_role`**. `on` is `str(settings.business_date)`, fixed per deployment (2026-10-23), so every event a session records falls inside the current period. The seed writes **no** `PAYMENT_STATUS_SET` (test_payment_status_adjust.py asserts `events(state) == []`). |
| Does an NPL declaration also write a status event? | Yes, measured through `POST /v1/cases/{uid}:advance` to `NPL_DECLARED_90` on C-002032. It wrote both:<ul><li>`journey.npl_cases` `npl-0212`, `declared_on` 2026-10-23</li><li>a SYSTEM `PAYMENT_STATUS_SET` LATE→NPL (the contract overlay → `follow_system_payment_status`)</li></ul>`CONFIRM_NPL` on a review does the same (`routers/journey.py:1073-1090`). So one customer can appear under both bases, and the figure counts both and names it. |
| First-touch pitfall | If the case store is first created **inside** the declaration request, `_seed` sees the contract already NON_PERFORMING. The case seeds NPL, `_follow` has nothing to follow, and **no event is written**. It is pre-existing and not fixed here. B13's tests call `cases.for_current()` before declaring. |
| NPL declarations at seed | `npl-0011`: C-002033, 2026-10-19, **inside** the period 2026-10-17..23. `npl-0013`: C-002034, 2026-09-14, outside. A declaration's customer is `jstate.cases[npl["case_uid"]]["customer_uid"]`; the `case_uid` is a journey case, not a `cases.py` case. |
| `_period(bd)` | `reports.py:104-107`: `end = bd`, `start = bd - 6`, returned as strings. At the default business date that is `2026-10-17..2026-10-23`. The prior 7 days are 2026-10-10..16. |
| OD-02 hold | Two sources:<ul><li>`reports._allocation_hold_in_period(cs, jstate, receipts)` (`reports.py:140-156`) returns `(customer_uids, receipt_uids)`: unallocated receipts in the period on a LATE/NPL case. `weekly()` already holds its result as `hold_customers` at `:179`.</li><li>The case's standing flag `allocation_hold` (`cases.py:294`), set by `set_allocation_hold` (`:513`) from `derive_dc_status("PAYMENT_CONFIRMED")` when arrears > 0. This happens on a slip, or on a KEPT PTP with **no receipt at all** (`routers/today.py` `close_case_ptp`).</li></ul>At seed: 0 and 0. |
| Service issues | Two registers:<ul><li>`cs.issues` (OPEN → RESOLVED, `cases.py:852`)</li><li>`jstate.issues` (OPEN / IN_PROGRESS / RESOLVED, `journey.py:581`; `open_issue_for` means "not RESOLVED", `journey.py:236`)</li></ul>`weekly()`'s existing `service_issues_open` counts only `cs.issues`. At seed: 0 case-register issues, 1 journey-register issue (IN_PROGRESS) on an in-collection customer with arrears 5,580.00 (SPV). |
| Receipts: entity, product, source | Every receipt carries `entity` + `company_id`, because `entities.entity_fields` raises for anything but SPV/EPC, so no receipt is unrouted. There is no product on a receipt; the customer comes through `journey.contract_by_uid(r["contract_uid"])`. `source` exists **only** on PEAK receipts (`"PEAK_REPORT"`, `journey.py:994`). Those receipts are `is_allocated = True` while `settings.peak_report_allocates` (F3, `config.py:185`) is on. At seed there are 2 receipts: 2026-09-10 EPC 20000 (C-002001) and 2026-08-28 EPC 399.00. The fixture path has no PEAK report (`customer.sheet["peak"]` is None). |
| Arrears per line | Contracts: 137 CASH/EPC and 76 LEASE/SPV; no customer spans two entities. `main._contract_view(k)[3].cumulative_arrears` summed per customer equals `item["aggregate_overdue"]` for all 151 in-collection items (9,081,825.88). 94 of them have arrears > 0. The extra per-contract pass costs 0.105 s; `reports.weekly()` went from 0.43 s to 0.54 s. |
| Payload pins | **No test asserts the weekly payload's exact key set.** `grep -rn "set(.*keys()) =="` over `backend/tests` finds three hits: `test_audit_store.py:163`, `test_peak_writer.py:136` and `test_round5_data_flow.py:410`. None is on the weekly payload. The readers are listed under B13's **Pins**. e2e (`scripts/e2e_check.py`) never calls `/v1/reports/weekly`. |
| Frontend on this branch | `screens/Reports.jsx` reads only keys already served (`:148-151`, `:306-308`, `:345-453`). `App.jsx:42,88` reads `management_summary`. None reads the five new keys, so B13 changes no frontend file. `components/WeeklyOverview.jsx` and `backend/app/weekly_export.py` do not exist here (`ls` at planning time). |
| Worktree at planning time | Another agent committed Round A fixes **during** planning: `c7d2552` and `b5bdc7c`. They touch `journey.py`, `routers/journey.py`, `attachments/guard.py`, `test_peak_book.py`, `test_attachments_guard.py`, `PeakReportCard.jsx` (+ test) and `i18n-admin.js`. One uncommitted edit to `attachments/guard.py` remained. B13 edits none of those files.<ul><li>`reports.py`, `cases.py`, `today.py` and `main.py` are byte-identical between `caddc4b` and `b5bdc7c`.</li><li>Line numbers in this section are `git show caddc4b:<path>` unless marked.</li><li>B13's three files, applied to a scratch copy of **`b5bdc7c`**, also ran the 10-file set at **220 passed**.</li></ul> |

---

### Task B13: The five weekly figures, served by `reports.weekly()`

**Files:**
- **Create `backend/app/weekly_figures.py`:** `build(...)` and the five block functions, `month_spans`, `peak_report_as_of`, and the `DEFINITIONS`/`SOURCES`/`NOTES` tables.
- **Modify `backend/app/reports.py`:**
  - `:10-11`: add `from . import weekly_figures`, between `from . import today as today_domain` and `from .config import settings`.
  - `:253-255`: spread `weekly_figures.build(...)` after `"reconciliation": reconciliation(),` inside `weekly()`'s return dict.
- **Create `backend/tests/test_weekly_figures.py`:** 17 tests.

**Interfaces:**
- **Consumes** (exact names, all at `caddc4b`):
  - From `reports.weekly()` (`reports.py:159-255`), passed in and never recomputed: `bd`, `start`/`end` (strings from `_period(bd)`), `items` (`today_domain.build()["items"]`), `cs` (`cases.for_current()`), `jstate` (`journey.for_current()`) and `hold_customers` (the first element of `_allocation_hold_in_period(...)`).
  - Journey lookups: `journey.book_customers()`, `journey.customer_by_uid(uid)`, `journey.contract_by_uid(uid) -> (customer, contract) | None`, `journey.open_issue_for(jstate, customer_uid) -> list`.
  - Money and case state: `main._contract_view(contract)[3].cumulative_arrears` (Decimal), `contract.entity` (`"SPV" | "EPC" | None`), `customer.sheet["peak"]["report_as_of"]`, `case["allocation_hold"]`, `cs.issues[*]["status" | "customer_uid"]`.
  - Stores: `cs.events[*]` (the `PAYMENT_STATUS_SET` keys above), `jstate.npl_cases[*]["uid" | "case_uid" | "declared_on" | "declared_by"]`, `jstate.cases[*]["customer_uid"]`, `jstate.receipts[*]["contract_uid" | "entity" | "amount" | "received_on" | "source"]`.
- **Produces:**
  - **`weekly_figures.build(business_date, period_start, period_end, items, cs, jstate, od02_receipt_customers) -> dict`** with exactly five keys. `GET /v1/reports/weekly` (and every snapshot payload, `reports.take_snapshot`) gains them beside its eleven existing keys.
  - **Common to every block:**
    - `definition` (EN) and `definition_th` (TH), the F15 sentence.
    - `source` (the stores read).
    - `notes: [{"code", "en", "th"}]`.
    - `empty: bool`.
    - Money is a string quantised to `0.01`, a percentage change is a string with one decimal and **no** `%` (like `ratio_late_pct`), or `None` when the base is 0.
  - **`mom`:**
    - `this_month` and `last_month` are each `{start, end, instalment, cash_or_project, total, receipts, peak_receipts}`.
    - `change` and `change_pct` are each `{instalment, cash_or_project, total}`.
    - Also: `measure: "cash_received"`, `peak_report_as_of: str|None`, `latest_receipt_on: str|None`, `indicative: bool`.
    - Note codes: `NO_RECEIPTS_ON_RECORD`, `NO_RECEIPTS_IN_SPAN`, `NO_BASE_FOR_PERCENT`, `NO_PEAK_REPORT`, `PEAK_REPORT_OLDER_THAN_SPAN`.
  - **`paying_customers`:**
    - `this_period` and `prior_period` are each `{start, end, customers, receipts, unresolved_receipts}`.
    - Also: `change: int`, `change_pct`, `latest_receipt_on`.
    - Note codes: `NO_RECEIPTS_ON_RECORD`, `NO_RECEIPTS_IN_SPAN`, `NO_BASE_FOR_PERCENT`, `UNRESOLVED_RECEIPTS`.
  - **`npl_movement`:**
    - `period: {start, end}`
    - `entered: {by_status_change, by_declaration, customers}`
    - `left: {by_status_change, customers}`
    - `rows: [{customer_uid, display_name, volt_id, direction: "ENTERED"|"LEFT", basis: "STATUS_CHANGE"|"DECLARATION", on, from, to, by, reason, npl_uid}]`
    - Note codes: `EVENT_LOG_FROM_SYSTEM_START` and `NO_NPL_EXIT_RECORD` (always), `DECLARATION_ALSO_STATUS_CHANGE`, `NO_NPL_MOVEMENT_IN_PERIOD`.
  - **`arrears_split`:**
    - `as_of`, `unit`, `unit_th`.
    - `true`, `held` and `total` are each `{instalment, cash_or_project, unrouted, total, customers}`.
    - `held_by: {od02_allocation, service_issue}`.
    - `held_rows: [{customer_uid, display_name, volt_id, reasons, instalment, cash_or_project, unrouted, total}]`, arrears descending. `reasons` ⊆ `OD02_RECEIPT_IN_PERIOD`, `OD02_CASE_HOLD`, `SERVICE_ISSUE_CASE`, `SERVICE_ISSUE_JOURNEY`.
    - Also: `pending_decision: "OD-02"`, `indicative: bool`.
    - Note codes: `NO_ARREARS`, `OD02_OPEN`, `TWO_ISSUE_REGISTERS`.
  - **`status_changes`:**
    - `period`, `rows: [{customer_uid, display_name, volt_id, case_uid, on, from, to, system, by, by_system, reason, ended}]`, `order: "newest first"`.
    - Also: `count`, `by_system`, `by_person`.
    - Note codes: `EVENT_LOG_FROM_SYSTEM_START` (always), `NO_STATUS_CHANGES_IN_PERIOD`.
  - **Also produced:** `weekly_figures.month_spans(business_date) -> ((date, date), (date, date))` and `weekly_figures.peak_report_as_of() -> str|None`.
  - **Consumed by B14** (blocked).
  - Test ids: every function in `backend/tests/test_weekly_figures.py` (below).
  - **i18n keys: none.** B13 serves sentences; B14 adds only chrome labels.
- **Unchanged:** every key served before, including `npl_changes` (NPL_TYPE_SET, last 10) and `management_summary.cash_in`.

**Pins:** **0 backend, 0 frontend, 0 density** (no screen changes).
- **Backend tests that read `/v1/reports/weekly`** were measured, and none asserts an exact key set:
  - `test_round1_p3.py:294-303`
  - `test_round2.py:304-307`, `:479`, `:487-489`
  - `test_round3.py:106-108`
  - `test_round4.py:132-133`, `:229-247`, `:327-335`, `:341-351`
  - `test_round5_kpi.py:349-352`
  - `test_today_and_pipeline.py:242-253`
  - `test_audit_coverage.py:98-99`
  - `test_auth_http.py:226-227`
- **Frontend fixtures that mock the payload** are untouched by a backend change: `round4.test.jsx:126-132`, `App.test.jsx:92,106`, `Dashboard.test.jsx:52,434-485`.
- **Measured run:** with B13 applied to a scratch copy of `caddc4b`, those eight files plus `test_payment_status_adjust.py` and the new file ran **220 passed** (no Postgres needed).

**Worktree rules for this task:**
- The backend interpreter is `backend/.venv/bin/python`. Run pytest without adding `-q`.
- `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data`, where `<task-db>` is assigned by the controller.
- Never set `DATABASE_URL` to `volt_local`. Never use a bare `git stash`. Never `cd` into `/Users/parattakorn/volt-debt-prototype`.
- Commit with a message file plus a pathspec. Never `git add -A`.

- [ ] **Step 1: Pre-flight — the tree and the baseline**

Run:
```bash
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 log --oneline -8
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 status --short
ls /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend/app/weekly_figures.py
```
Expected:
- HEAD at `b5bdc7c` or later (`caddc4b` plus two Round A fix commits that do not touch B13's files).
- `weekly_figures.py`: "No such file or directory".
- `status --short` lists **none** of `backend/app/reports.py`, `backend/app/weekly_figures.py` or `backend/tests/test_weekly_figures.py`. If another agent's uncommitted edits are listed (planning time saw Task 25c's), leave them alone and do not commit them. The pathspec in Step 8 keeps them out.

Then confirm the anchors this task edits are unchanged:
```bash
grep -n "^from . import today as today_domain$\|^from .config import settings$\|\"reconciliation\": reconciliation(),$\|hold_customers, hold_receipts = _allocation_hold_in_period" /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend/app/reports.py
grep -n "\"kind\": \"PAYMENT_STATUS_SET\"" /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend/app/cases.py
```
Expected (at `caddc4b`):
- reports.py: `10:from . import today as today_domain`, `11:from .config import settings`, `179:    hold_customers, hold_receipts = …`, `254:        "reconciliation": reconciliation(),`.
- cases.py: two hits, `196` and `1024`.

If either event site's key set differs from `from, code, system, by, reason, on, ended`, stop and report: another cluster changed the event contract.

Record the backend baseline, pasting the line:
```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest 2>&1 | tail -1
```
Expected: the count the controller last recorded for HEAD. The brief's figure is `1022 passed, 11 skipped` at `caddc4b`; `c7d2552` and `b5bdc7c` add tests, so HEAD's count is higher and was not measured by the planner.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_weekly_figures.py
"""Feedback Round 1, WP12 (design F15): the five weekly figures the API did not send.

Every block is served by reports.weekly() beside the keys it already served, with its
definition line in Thai and English, and notes that say when its source is empty or
the figure is indicative — never a silent 0.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cases, journey, main, reports, weekly_figures
from app import today as today_domain
from app.book import SHEET
from app.config import settings
from app.main import app

BD = settings.business_date                       # 2026-10-23; the period is 10-17..10-23
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}
FIVE = ("mom", "paying_customers", "npl_movement", "arrears_split", "status_changes")
SERVED_BEFORE = {"period", "management_summary", "portfolio", "promises", "npl_changes", "power_actions",
                 "service_issues_open", "reviews_open", "next_week_focus", "counts_by_tier", "reconciliation"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


def _codes(block):
    return [n["code"] for n in block["notes"]]


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")        # the session reports.weekly() reads outside a request
    return c


def _customer(product, nth=0):
    rows = [c for c in journey.book_customers() if c.contracts and c.contracts[0].product == product]
    return rows[nth]


def _receipt(customer, amount, on, source=None):
    contract = customer.contracts[0]
    rcp = journey.make_receipt(journey.for_current(), contract.uid, contract.entity, amount, on)
    if source:
        rcp["source"] = source
    return rcp


# --- the shape ----------------------------------------------------------------------

def test_the_five_figures_are_served_beside_every_key_served_before(client):
    body = client.get("/v1/reports/weekly").json()
    assert SERVED_BEFORE <= set(body)
    for key in FIVE:
        block = body[key]
        assert block["definition"] and _thai(block["definition_th"]) and block["source"], key
        assert isinstance(block["notes"], list), key
        for note in block["notes"]:
            assert note["code"] and note["en"] and _thai(note["th"]), (key, note)


def test_a_snapshot_freezes_the_five_figures_too(client):
    snap = client.post("/v1/reports/weekly:snapshot", headers=OWNER).json()["snapshot"]
    assert set(FIVE) <= set(snap["payload"])


# --- MoM ------------------------------------------------------------------------------

def test_the_month_spans_stop_on_the_same_day_and_clip_to_a_short_month():
    assert weekly_figures.month_spans(date(2026, 10, 23)) == (
        (date(2026, 10, 1), date(2026, 10, 23)), (date(2026, 9, 1), date(2026, 9, 23)))
    assert weekly_figures.month_spans(date(2026, 3, 31)) == (
        (date(2026, 3, 1), date(2026, 3, 31)), (date(2026, 2, 1), date(2026, 2, 28)))
    assert weekly_figures.month_spans(date(2026, 1, 15)) == (
        (date(2026, 1, 1), date(2026, 1, 15)), (date(2025, 12, 1), date(2025, 12, 15)))


def test_at_seed_this_month_is_an_empty_span_said_in_words_not_a_bare_zero():
    mom = reports.weekly()["mom"]
    assert mom["this_month"] == {"start": "2026-10-01", "end": "2026-10-23", "instalment": "0.00",
                                 "cash_or_project": "0.00", "total": "0.00", "receipts": 0, "peak_receipts": 0}
    # the seed's C-002001 deposit (2026-09-10, EPC 20,000) is inside 1-23 Sep; 2026-08-28 is not
    assert mom["last_month"]["cash_or_project"] == "20000.00" and mom["last_month"]["receipts"] == 1
    assert mom["change"] == {"instalment": "0.00", "cash_or_project": "-20000.00", "total": "-20000.00"}
    assert mom["change_pct"] == {"instalment": None, "cash_or_project": "-100.0", "total": "-100.0"}
    assert mom["latest_receipt_on"] == "2026-09-10" and mom["empty"] is False
    codes = _codes(mom)
    assert "NO_RECEIPTS_IN_SPAN" in codes and "NO_BASE_FOR_PERCENT" in codes
    empty = next(n for n in mom["notes"] if n["code"] == "NO_RECEIPTS_IN_SPAN")
    assert "2026-10-01" in empty["th"] and "2026-09-10" in empty["th"]
    # the fixture book has no applied PEAK report, so the month is partial and says so
    assert mom["peak_report_as_of"] is None and mom["indicative"] is True and "NO_PEAK_REPORT" in codes


def test_mom_splits_spv_from_epc_and_serves_every_change():
    lease, cash = _customer("LEASE"), _customer("CASH")
    _receipt(lease, "8399.00", BD - timedelta(days=3))
    _receipt(lease, "100.50", date(2026, 9, 2))
    _receipt(cash, "5000.00", date(2026, 10, 1))
    _receipt(cash, "999.00", date(2026, 9, 24))              # the day after last month's span: not counted
    mom = reports.weekly()["mom"]
    assert (mom["this_month"]["instalment"], mom["this_month"]["cash_or_project"], mom["this_month"]["total"]) == \
        ("8399.00", "5000.00", "13399.00")
    assert (mom["last_month"]["instalment"], mom["last_month"]["cash_or_project"], mom["last_month"]["total"]) == \
        ("100.50", "20000.00", "20100.50")
    assert mom["change"] == {"instalment": "8298.50", "cash_or_project": "-15000.00", "total": "-6701.50"}
    assert mom["change_pct"] == {"instalment": "8257.2", "cash_or_project": "-75.0", "total": "-33.3"}
    assert "NO_RECEIPTS_IN_SPAN" not in _codes(mom) and "NO_BASE_FOR_PERCENT" not in _codes(mom)


def test_a_peak_receipt_counts_and_an_older_report_badges_the_month_indicative():
    customer = next(c for c in journey.book_customers()
                    if c.data_source == SHEET and len(c.contracts) == 1 and c.contracts[0].product == "LEASE"
                    and cases.contract_field_of(c.contracts[0], "status") == "PAST_DUE")
    paid = {"doc_no": "IVT-9", "doc_kind": "IVT", "issued_on": "2026-10-01", "due_on": "2026-10-05", "status": "PAID",
            "cycle": {"n": 9, "of": 48}, "product_group": "Solar Leasing", "amount_total": "8399.00",
            "amount_due": "8399.00", "amount_awaiting": "0.00",
            "payment": {"on": "2026-10-08", "channel": "Beam", "amount": "8399.00", "receipt_no": "RE-9"},
            "contact_code": "VC1", "rule": "CUSTOMER_NO"}
    customer.sheet = dict(customer.sheet, peak={"report_as_of": "2026-10-10", "run_id": 1, "invoices": [paid]})
    journey.reset()
    mom = reports.weekly()["mom"]
    assert mom["this_month"]["instalment"] == "8399.00" and mom["this_month"]["peak_receipts"] == 1
    assert mom["peak_report_as_of"] == "2026-10-10" and mom["indicative"] is True
    older = next(n for n in mom["notes"] if n["code"] == "PEAK_REPORT_OLDER_THAN_SPAN")
    assert "2026-10-10" in older["th"] and "NO_PEAK_REPORT" not in _codes(mom)


# --- paying customers, WoW ------------------------------------------------------------

def test_paying_customers_count_each_customer_once_against_the_seven_days_before():
    a, b, c = _customer("LEASE", 0), _customer("CASH", 0), _customer("CASH", 1)
    _receipt(a, "100.00", BD)
    _receipt(a, "100.00", BD - timedelta(days=6))           # 10-17, the first day of the period
    _receipt(b, "100.00", BD - timedelta(days=2))
    _receipt(c, "100.00", BD - timedelta(days=7))           # 10-16, the last day of the prior period
    journey.make_receipt(journey.for_current(), "K-NOT-IN-BOOK", "EPC", "50.00", BD - timedelta(days=1))
    paying = reports.weekly()["paying_customers"]
    assert paying["this_period"] == {"start": "2026-10-17", "end": "2026-10-23", "customers": 2, "receipts": 4,
                                     "unresolved_receipts": 1}
    assert paying["prior_period"] == {"start": "2026-10-10", "end": "2026-10-16", "customers": 1, "receipts": 1,
                                      "unresolved_receipts": 0}
    assert paying["change"] == 1 and paying["change_pct"] == "100.0"
    assert "UNRESOLVED_RECEIPTS" in _codes(paying) and "NO_RECEIPTS_IN_SPAN" not in _codes(paying)


def test_with_no_receipt_in_either_week_the_zero_says_why():
    payload = reports.weekly()
    paying = payload["paying_customers"]
    assert paying["this_period"]["start"] == payload["period"]["start"]
    assert (paying["this_period"]["customers"], paying["prior_period"]["customers"]) == (0, 0)
    assert paying["change"] == 0 and paying["change_pct"] is None and paying["empty"] is True
    assert _codes(paying).count("NO_RECEIPTS_IN_SPAN") == 2 and "NO_BASE_FOR_PERCENT" in _codes(paying)


def test_with_no_receipt_on_record_at_all_the_note_says_that_instead():
    journey.for_current().receipts.clear()
    paying = reports.weekly()["paying_customers"]
    assert paying["latest_receipt_on"] is None
    assert "NO_RECEIPTS_ON_RECORD" in _codes(paying) and "NO_RECEIPTS_IN_SPAN" not in _codes(paying)


# --- NPL in / out -----------------------------------------------------------------------

def _journey_case_of(client, customer_no):
    # Touch the case store BEFORE declaring. Measured: when the store is first created
    # inside the declaration, it seeds the case already NPL (the contract overlay is
    # written first), so the system has nothing to follow and writes no event. A real
    # session has always opened Today before a declaration.
    cases.for_current()
    return next(c for c in client.get("/v1/cases").json()["cases"]
                if main.BY_CUSTOMER[c["customer_uid"]].customer_no == customer_no)


def test_at_seed_the_one_declaration_inside_the_period_is_counted_by_its_basis():
    npl = reports.weekly()["npl_movement"]
    # C-002033 was declared 2026-10-19 (inside); C-002034 on 2026-09-14 (outside)
    assert npl["entered"] == {"by_status_change": 0, "by_declaration": 1, "customers": 1}
    assert npl["left"] == {"by_status_change": 0, "customers": 0}
    [row] = npl["rows"]
    assert (row["direction"], row["basis"], row["on"], row["to"]) == ("ENTERED", "DECLARATION", "2026-10-19", "NPL")
    assert main.BY_CUSTOMER[row["customer_uid"]].customer_no == "C-002033" and row["npl_uid"]
    assert "EVENT_LOG_FROM_SYSTEM_START" in _codes(npl) and "NO_NPL_EXIT_RECORD" in _codes(npl)


def test_a_declaration_counts_twice_by_basis_once_by_customer_and_a_person_moving_out_counts_as_left(client):
    declared = client.post("/v1/cases/%s:advance" % _journey_case_of(client, "C-002032")["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    assert declared.status_code == 200
    back = next(c for c in cases.for_current().cases.values() if c["customer_no"] == "C-002034")
    moved = client.post("/v1/cases/by-customer/%s/payment-status" % back["customer_uid"],
                        json={"code": "LATE", "reason": "ลูกค้าเริ่มชำระตามแผน"}, headers={"X-Volt-Officer": "settasak"})
    assert moved.status_code == 200
    npl = client.get("/v1/reports/weekly").json()["npl_movement"]
    assert npl["entered"] == {"by_status_change": 1, "by_declaration": 2, "customers": 2}
    assert npl["left"] == {"by_status_change": 1, "customers": 1}
    both = next(n for n in npl["notes"] if n["code"] == "DECLARATION_ALSO_STATUS_CHANGE")
    assert "1" in both["th"]
    left = next(r for r in npl["rows"] if r["direction"] == "LEFT")
    assert (left["from"], left["to"], left["by"], left["reason"]) == ("NPL", "LATE", "settasak", "ลูกค้าเริ่มชำระตามแผน")


# --- true vs held arrears -----------------------------------------------------------------

def _late_with_arrears(state, skip=()):
    for case in state.cases.values():
        if case["payment_status"] != "LATE" or case["customer_uid"] in skip or case["open_issue_uid"]:
            continue
        if cases.case_arrears(case) > 0 and not journey.open_issue_for(journey.for_current(), case["customer_uid"]):
            return case
    raise AssertionError("no LATE case with arrears and no open issue")


def test_the_split_reconciles_to_the_items_arrears_line_by_line():
    payload = reports.weekly()
    split = payload["arrears_split"]
    items = today_domain.build()["items"]
    assert Decimal(split["total"]["total"]) == sum((Decimal(i["aggregate_overdue"]) for i in items), Decimal("0"))
    for side in ("true", "held", "total"):
        block = split[side]
        assert Decimal(block["total"]) == Decimal(block["instalment"]) + Decimal(block["cash_or_project"]) + Decimal(block["unrouted"])
    for line in ("instalment", "cash_or_project", "unrouted", "total"):
        assert Decimal(split["total"][line]) == Decimal(split["true"][line]) + Decimal(split["held"][line])
    assert split["total"]["customers"] == split["true"]["customers"] + split["held"]["customers"]
    assert split["as_of"] == str(BD) and _thai(split["unit_th"])


def test_an_od02_hold_and_an_open_issue_move_a_customer_from_true_to_held_and_say_why():
    state = cases.for_current()
    before = reports.weekly()["arrears_split"]
    held = _late_with_arrears(state)
    cases.set_allocation_hold(held, cases.case_arrears(held))
    ticket = _late_with_arrears(state, skip={held["customer_uid"]})
    cases.log_contact(state, ticket, {"result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
                                      "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M"}},
                      by="nantapol")
    split = reports.weekly()["arrears_split"]
    assert split["held"]["customers"] == before["held"]["customers"] + 2
    assert split["true"]["customers"] == before["true"]["customers"] - 2
    rows = {r["customer_uid"]: r for r in split["held_rows"]}
    assert rows[held["customer_uid"]]["reasons"] == ["OD02_CASE_HOLD"]
    assert rows[ticket["customer_uid"]]["reasons"] == ["SERVICE_ISSUE_CASE"]
    assert split["held_by"]["od02_allocation"] >= 1 and split["held_by"]["service_issue"] >= 1
    assert split["indicative"] is True and split["pending_decision"] == "OD-02"
    assert {"OD02_OPEN", "TWO_ISSUE_REGISTERS"} <= set(_codes(split))


def test_a_receipt_in_the_period_on_a_late_case_is_held_by_the_same_rule_as_the_portfolio_caveat():
    state = cases.for_current()
    case = _late_with_arrears(state)
    contract = main.BY_CUSTOMER[case["customer_uid"]].contracts[0]
    journey.make_receipt(journey.for_current(), contract.uid, contract.entity, "100.00", BD)
    payload = reports.weekly()
    row = next(r for r in payload["arrears_split"]["held_rows"] if r["customer_uid"] == case["customer_uid"])
    assert "OD02_RECEIPT_IN_PERIOD" in row["reasons"]
    assert payload["portfolio"]["allocation_hold_customers"] >= 1


# --- every status change ----------------------------------------------------------------

def test_every_payment_status_change_in_the_period_is_listed_newest_first_with_who_and_why(client):
    state = cases.for_current()
    first, second = [c for c in state.cases.values() if c["payment_status"] == "LATE"][:2]
    client.post("/v1/cases/by-customer/%s/payment-status" % first["customer_uid"],
                json={"code": "CURRENT", "reason": "โอนครบแล้ว รอ PEAK"}, headers={"X-Volt-Officer": "thip"})
    client.post("/v1/cases/by-customer/%s/payment-status" % second["customer_uid"],
                json={"code": "NPL", "reason": "ผิดนัดสามงวด"}, headers={"X-Volt-Officer": "nantapol"})
    changes = client.get("/v1/reports/weekly").json()["status_changes"]
    assert changes["count"] == 2 and changes["by_person"] == 2 and changes["by_system"] == 0
    newest, older = changes["rows"]
    assert (newest["from"], newest["to"], newest["by"], newest["reason"]) == ("LATE", "NPL", "nantapol", "ผิดนัดสามงวด")
    assert (older["from"], older["to"], older["by"]) == ("LATE", "CURRENT", "thip")
    assert newest["system"] == "LATE" and newest["on"] == str(BD) and newest["display_name"]
    assert changes["order"] == "newest first" and changes["empty"] is False


def test_a_status_the_system_followed_is_listed_as_the_systems(client):
    client.post("/v1/cases/%s:advance" % _journey_case_of(client, "C-002032")["uid"],
                json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    changes = client.get("/v1/reports/weekly").json()["status_changes"]
    [row] = changes["rows"]
    assert row["by"] == "SYSTEM" and row["by_system"] is True and row["reason"] is None
    assert changes["by_system"] == 1


def test_with_no_change_in_the_period_the_list_is_empty_and_says_so():
    changes = reports.weekly()["status_changes"]
    assert changes["rows"] == [] and changes["count"] == 0 and changes["empty"] is True
    assert "NO_STATUS_CHANGES_IN_PERIOD" in _codes(changes)
```

What each test pins, in one line each:
- **The shape:**
  - every block has both definition lines, a source and Thai notes
  - the eleven old keys stay
  - a snapshot freezes the five
- **MoM:**
  - the span rule, including 31 March → 1–28 February and January → December
  - the seed's empty October is said in words (with the latest receipt's date), not left as a bare 0
  - SPV vs EPC and every change and percentage are served
  - a PEAK receipt counts, and an older report makes the month `indicative`
- **Paying customers:**
  - distinct customers, both period edges (10-17 inside, 10-16 prior)
  - a receipt on a contract outside the book is named, not counted
  - both empty states
- **NPL in/out:**
  - the seeded declaration inside the period
  - a new declaration counts under both bases but once by customer
  - a person moving NPL → LATE counts as left, with who and why
- **True vs held:**
  - the split reconciles line by line to the items' `aggregate_overdue`
  - an OD-02 case hold and a case-register ticket move two customers from true to held and say why
  - an unallocated receipt in the period is held by the same rule as `portfolio.allocation_hold_customers`
- **Status changes:**
  - two person changes, newest first, with from/to/by/reason
  - a SYSTEM change is labelled as the system's
  - the empty period says so

- [ ] **Step 3: Run them and watch them fail**

Run:
```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest tests/test_weekly_figures.py
```
Expected (measured on a pristine copy of `caddc4b`): `ERROR tests/test_weekly_figures.py`, with `ImportError: cannot import name 'weekly_figures' from 'app'` and `1 error during collection`.

- [ ] **Step 4: Write the module**

```python
# backend/app/weekly_figures.py
"""The five weekly figures the report did not serve — Feedback Round 1, WP12 (design F15).

`reports.weekly()` spreads `build(...)` into its payload, beside the keys it already
served; nothing it served before changes. Each figure is computed once, here:

  mom               this calendar month's receipts vs the same span of last month
  paying_customers  distinct customers with a receipt, this 7-day period vs the 7 before
  npl_movement      into / out of NPL in the period: status changes AND declarations
  arrears_split     arrears held on the company side (OD-02 hold, open service issue)
                    vs true arrears, per instalment / cash line
  status_changes    every PAYMENT_STATUS_SET in the period (from -> to, by, reason)

House rules carried here:
  - Money is Decimal, served as strings quantised to 0.01. The client never adds
    (api.js:1-4) — every total and every change is on the wire.
  - Every figure carries `definition` / `definition_th` (the F15 sentence) and
    `source` (the stores it reads).
  - `notes` is a list of {code, en, th}. A zero whose source is empty says so, and a
    figure known to be partial says so and sets `indicative` — never a silent 0 that
    reads as "nobody paid".
  - Read-only: nothing here writes to any store.
"""
from datetime import timedelta
from decimal import Decimal

from . import journey

CENT = Decimal("0.01")
# The one routing rule (entities.py): SPV carries the lease instalments, EPC the cash
# and project receivables AND every service fee. The same two keys `cash_in` already
# serves, so the new figures and the old one name their lines alike.
LINE_OF_ENTITY = {"SPV": "instalment", "EPC": "cash_or_project"}
RECEIPT_LINES = ("instalment", "cash_or_project")
# A contract whose product has no entity stays unrouted, visibly (fixtures.py) —
# its arrears land here, never in a guessed line.
ARREARS_LINES = ("instalment", "cash_or_project", "unrouted")

DEFINITIONS = {
    "mom": (
        "Receipts this calendar month (day 1 to the business date) against the same span of "
        "last month, split instalment (SPV) and cash/project (EPC, service fees included). "
        "Counted from the receipts on record, including an applied PEAK report's receipts.",
        "ยอดรับเงินเดือนนี้ (วันที่ 1 ถึงวันทำการ) เทียบช่วงวันเดียวกันของเดือนก่อน แยกค่างวด (SPV) "
        "และเงินสด/โครงการ (EPC รวมค่าบริการ) นับจากใบเสร็จในระบบ รวมใบเสร็จจากรายงาน PEAK ที่ใช้งานแล้ว",
    ),
    "paying_customers": (
        "Distinct customers with at least one receipt in this 7-day period, against the 7 days before it.",
        "จำนวนลูกค้าที่มีใบเสร็จอย่างน้อย 1 ใบในช่วง 7 วันนี้ (นับหัวไม่ซ้ำ) เทียบกับ 7 วันก่อนหน้า",
    ),
    "npl_movement": (
        "Into NPL: payment-status changes to NPL in the period, and NPL declarations opened in the "
        "period; both are counted, and `customers` counts each customer once. Out of NPL: "
        "payment-status changes from NPL to any other status in the period.",
        "เข้า NPL: การเปลี่ยนสถานะการชำระเป็น NPL ในช่วงนี้ และการประกาศ NPL ที่เปิดในช่วงนี้ "
        "นับทั้งสองแบบ และช่องลูกค้านับหัวไม่ซ้ำ · ออกจาก NPL: การเปลี่ยนสถานะจาก NPL เป็นค่าอื่นในช่วงนี้",
    ),
    "arrears_split": (
        "Arrears of the customers in collection on the business date, per instalment and cash line. "
        "Held on the company side: the customer is under an OD-02 allocation hold or has an open "
        "service issue. True arrears: every other customer.",
        "ยอดค้างของลูกค้าที่อยู่ในการติดตาม ณ วันทำการ แยกค่างวดและเงินสด · พักไว้ฝั่งบริษัท = ลูกค้าที่รอจัดสรรเงิน "
        "(OD-02) หรือมีตั๋วปัญหาบริการเปิดอยู่ · ค้างจริง = ลูกค้าที่เหลือทั้งหมด",
    ),
    "status_changes": (
        "Every payment-status change in the period — from, to, who and why — whether a person "
        "made it or the system followed the data.",
        "ทุกการเปลี่ยนสถานะการชำระในช่วงนี้ (จาก → เป็น ใครเปลี่ยน เหตุผล) ทั้งที่คนเปลี่ยนเองและที่ระบบปรับตามข้อมูล",
    ),
}

SOURCES = {
    "mom": "journey.receipts (slips, recorded receipts, PEAK report receipts: source PEAK_REPORT)",
    "paying_customers": "journey.receipts, customer by the receipt's contract",
    "npl_movement": "cases.events PAYMENT_STATUS_SET; journey.npl_cases declared_on",
    "arrears_split": "money engine per contract; OD-02 hold (receipts in the period + case allocation_hold); "
                     "open service issues in cases.issues and journey.issues",
    "status_changes": "cases.events PAYMENT_STATUS_SET",
}

NOTES = {
    "NO_RECEIPTS_ON_RECORD": (
        "No receipt is on record at all: 0 means nothing was recorded, not that nobody paid.",
        "ยังไม่มีใบเสร็จในระบบเลย — 0 คือไม่มีบันทึกการรับเงิน ไม่ใช่ยืนยันว่าไม่มีใครจ่าย",
    ),
    "NO_RECEIPTS_IN_SPAN": (
        "No receipt from {start} to {end}: 0 means nothing was recorded, not that nobody paid. "
        "The latest receipt on record is dated {latest}.",
        "ไม่มีใบเสร็จช่วง {start} ถึง {end} — 0 คือไม่มีบันทึกการรับเงิน ไม่ใช่ยืนยันว่าไม่มีใครจ่าย "
        "(ใบเสร็จล่าสุดในระบบลงวันที่ {latest})",
    ),
    "NO_PEAK_REPORT": (
        "No PEAK report is applied, so only receipts recorded in this system are counted.",
        "ยังไม่มีรายงาน PEAK ที่ใช้งาน จึงนับเฉพาะใบเสร็จที่บันทึกในระบบนี้",
    ),
    "PEAK_REPORT_OLDER_THAN_SPAN": (
        "The applied PEAK report is as of {as_of}; receipts after that date are not in yet, so this month is incomplete.",
        "รายงาน PEAK ที่ใช้อยู่เป็นข้อมูล ณ {as_of} ใบเสร็จหลังวันนั้นยังไม่เข้า ตัวเลขเดือนนี้จึงยังไม่ครบ",
    ),
    "NO_BASE_FOR_PERCENT": (
        "Where the earlier span is 0, no percentage change can be given.",
        "ช่องที่ช่วงก่อนหน้าเป็น 0 คิดเป็นร้อยละการเปลี่ยนแปลงไม่ได้",
    ),
    "UNRESOLVED_RECEIPTS": (
        "{n} receipt(s) name a contract the book does not hold, so they are not counted as a customer.",
        "ใบเสร็จ {n} ใบอ้างสัญญาที่ไม่อยู่ในสมุดงาน จึงไม่นับเป็นลูกค้า",
    ),
    "EVENT_LOG_FROM_SYSTEM_START": (
        "Counted from the status changes recorded in this system; a change made before it (on the sheet) has no record.",
        "นับจากบันทึกการเปลี่ยนสถานะที่เกิดในระบบนี้ การเปลี่ยนก่อนเริ่มใช้ระบบ (ในชีต) ไม่มีบันทึก",
    ),
    "DECLARATION_ALSO_STATUS_CHANGE": (
        "{n} customer(s) entered NPL by a declaration that also changed the payment status; both rows are "
        "listed, and `customers` counts each customer once.",
        "ลูกค้า {n} รายเข้า NPL จากการประกาศที่ทำให้สถานะการชำระเปลี่ยนด้วย จึงแสดงทั้งสองแถว แต่ช่องลูกค้านับหัวไม่ซ้ำ",
    ),
    "NO_NPL_EXIT_RECORD": (
        "Leaving NPL is counted from status changes only; the system has no record that closes a declaration.",
        "การออกจาก NPL นับจากการเปลี่ยนสถานะเท่านั้น ระบบยังไม่มีบันทึกการปิดการประกาศ NPL",
    ),
    "NO_NPL_MOVEMENT_IN_PERIOD": (
        "No customer entered or left NPL in the period.",
        "ไม่มีลูกค้าเข้าหรือออกจาก NPL ในช่วงนี้",
    ),
    "NO_STATUS_CHANGES_IN_PERIOD": (
        "No payment status changed in the period.",
        "ไม่มีการเปลี่ยนสถานะการชำระในช่วงนี้",
    ),
    "NO_ARREARS": (
        "No customer in collection has arrears on the business date.",
        "ไม่มีลูกค้าในการติดตามที่มียอดค้าง ณ วันทำการ",
    ),
    "OD02_OPEN": (
        "Held arrears include {n} customer(s) whose money is in but not allocated while OD-02 is open, so their "
        "arrears have not moved.",
        "ยอดพักไว้รวมลูกค้า {n} รายที่รับเงินแล้วแต่ยังไม่จัดสรร (รอ OD-02) ยอดค้างของลูกค้ากลุ่มนี้จึงยังไม่ลด",
    ),
    "TWO_ISSUE_REGISTERS": (
        "Open service issues are read from both registers: the case's ticket and the service-issue desk.",
        "ตั๋วปัญหาบริการนับจากทั้งสองทะเบียน คือตั๋วบนเคส และงานปัญหาบริการ",
    ),
}


def _note(code, **values):
    en, th = NOTES[code]
    return {"code": code, "en": en.format(**values), "th": th.format(**values)}


def _definition(key):
    en, th = DEFINITIONS[key]
    return {"definition": en, "definition_th": th, "source": SOURCES[key]}


def _money(value):
    return str(Decimal(value).quantize(CENT))


def _pct(now, before):
    """Percentage change, one decimal, as a string; None when there is no base."""
    now, before = Decimal(now), Decimal(before)
    if before == 0:
        return None
    return str(((now - before) / before * 100).quantize(Decimal("0.1")))


def _day(value):
    return str(value)[:10] if value else None


def _inside(value, start, end):
    day = _day(value)
    return bool(day) and str(start) <= day <= str(end)


def _in_span(receipts, start, end):
    return [r for r in receipts if _inside(r.get("received_on"), start, end)]


def _latest_receipt_on(receipts):
    days = [_day(r.get("received_on")) for r in receipts if r.get("received_on")]
    return max(days) if days else None


def month_spans(business_date):
    """((this_start, this_end), (last_start, last_end)) as dates. Last month's span stops
    on the same day number, clipped to that month's last day (31 Mar -> 1-28 Feb)."""
    this_start = business_date.replace(day=1)
    last_month_end = this_start - timedelta(days=1)
    last_start = last_month_end.replace(day=1)
    last_end = last_start.replace(day=min(business_date.day, last_month_end.day))
    return (this_start, business_date), (last_start, last_end)


def peak_report_as_of():
    """The applied PEAK report's date, from the one seam the book carries it on
    (customer.sheet["peak"]["report_as_of"], as payment_position reads it); None when
    no report is applied."""
    dates = []
    for customer in journey.book_customers():
        peak = (getattr(customer, "sheet", None) or {}).get("peak") or {}
        if peak.get("report_as_of"):
            dates.append(str(peak["report_as_of"]))
    return max(dates) if dates else None


def _money_span(receipts, start, end):
    rows = _in_span(receipts, start, end)
    sums = {line: Decimal("0") for line in RECEIPT_LINES}
    for r in rows:
        sums[LINE_OF_ENTITY[r["entity"]]] += Decimal(str(r["amount"]))
    out = {"start": str(start), "end": str(end)}
    out.update({line: _money(sums[line]) for line in RECEIPT_LINES})
    out["total"] = _money(sum(sums.values(), Decimal("0")))
    out["receipts"] = len(rows)
    out["peak_receipts"] = sum(1 for r in rows if r.get("source") == "PEAK_REPORT")
    return out


def mom(business_date, receipts):
    (this_start, this_end), (last_start, last_end) = month_spans(business_date)
    this = _money_span(receipts, this_start, this_end)
    last = _money_span(receipts, last_start, last_end)
    keys = RECEIPT_LINES + ("total",)
    change = {k: _money(Decimal(this[k]) - Decimal(last[k])) for k in keys}
    change_pct = {k: _pct(this[k], last[k]) for k in keys}
    latest = _latest_receipt_on(receipts)
    as_of = peak_report_as_of()
    notes = []
    if latest is None:
        notes.append(_note("NO_RECEIPTS_ON_RECORD"))
    else:
        for span in (this, last):
            if span["receipts"] == 0:
                notes.append(_note("NO_RECEIPTS_IN_SPAN", start=span["start"], end=span["end"], latest=latest))
    if any(v is None for v in change_pct.values()):
        notes.append(_note("NO_BASE_FOR_PERCENT"))
    if as_of is None:
        notes.append(_note("NO_PEAK_REPORT"))
    elif as_of < this["end"]:
        notes.append(_note("PEAK_REPORT_OLDER_THAN_SPAN", as_of=as_of))
    return dict(_definition("mom"), this_month=this, last_month=last, change=change, change_pct=change_pct,
                measure="cash_received", peak_report_as_of=as_of, latest_receipt_on=latest,
                # The month is known to be partial whenever PEAK's receipts do not reach its last day.
                indicative=as_of is None or as_of < this["end"],
                empty=this["receipts"] == 0 and last["receipts"] == 0, notes=notes)


def _paying_span(receipts, start, end):
    rows = _in_span(receipts, start, end)
    customers, unresolved = set(), 0
    for r in rows:
        found = journey.contract_by_uid(r["contract_uid"])
        if found:
            customers.add(found[0].uid)
        else:
            unresolved += 1
    return {"start": str(start), "end": str(end), "customers": len(customers), "receipts": len(rows),
            "unresolved_receipts": unresolved}


def paying_customers(period_start, period_end, receipts):
    prior_end = period_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    this = _paying_span(receipts, period_start, period_end)
    prior = _paying_span(receipts, prior_start, prior_end)
    latest = _latest_receipt_on(receipts)
    notes = []
    if latest is None:
        notes.append(_note("NO_RECEIPTS_ON_RECORD"))
    else:
        for span in (this, prior):
            if span["receipts"] == 0:
                notes.append(_note("NO_RECEIPTS_IN_SPAN", start=span["start"], end=span["end"], latest=latest))
    change_pct = _pct(this["customers"], prior["customers"])
    if change_pct is None:
        notes.append(_note("NO_BASE_FOR_PERCENT"))
    unresolved = this["unresolved_receipts"] + prior["unresolved_receipts"]
    if unresolved:
        notes.append(_note("UNRESOLVED_RECEIPTS", n=unresolved))
    return dict(_definition("paying_customers"), this_period=this, prior_period=prior,
                change=this["customers"] - prior["customers"], change_pct=change_pct,
                latest_receipt_on=latest, empty=this["receipts"] == 0 and prior["receipts"] == 0, notes=notes)


def _who(customer_uid, cs):
    customer = journey.customer_by_uid(customer_uid) if customer_uid else None
    case = cs.cases.get(customer_uid) if customer_uid else None
    return {"customer_uid": customer_uid,
            "display_name": customer.display_name if customer else None,
            "volt_id": case.get("volt_id") if case else None}


def _status_events_in(cs, start, end):
    """PAYMENT_STATUS_SET events in the period, with the customer they belong to."""
    by_case_uid = {c["uid"]: c for c in cs.cases.values()}
    out = []
    for e in cs.events:
        if e.get("kind") != "PAYMENT_STATUS_SET" or not _inside(e.get("on"), start, end):
            continue
        case = by_case_uid.get(e.get("case_uid"))
        out.append((e, case["customer_uid"] if case else None))
    return out


def npl_movement(period_start, period_end, cs, jstate):
    rows = []
    entered, left, declared, changed_in = set(), set(), set(), set()
    by_change_in = by_change_out = by_declaration = 0
    for e, customer_uid in _status_events_in(cs, period_start, period_end):
        key = customer_uid or e.get("case_uid")
        into = e.get("code") == "NPL" and e.get("from") != "NPL"
        out = e.get("from") == "NPL" and e.get("code") != "NPL"
        if not (into or out):
            continue
        if into:
            by_change_in += 1
            entered.add(key)
            changed_in.add(key)
        else:
            by_change_out += 1
            left.add(key)
        rows.append(dict(_who(customer_uid, cs), direction="ENTERED" if into else "LEFT", basis="STATUS_CHANGE",
                         on=_day(e.get("on")), **{"from": e.get("from")}, to=e.get("code"), by=e.get("by"),
                         reason=e.get("reason"), npl_uid=None))
    for npl in jstate.npl_cases.values():
        if not _inside(npl.get("declared_on"), period_start, period_end):
            continue
        jcase = jstate.cases.get(npl.get("case_uid"))
        customer_uid = jcase["customer_uid"] if jcase else None
        key = customer_uid or npl.get("case_uid")
        by_declaration += 1
        entered.add(key)
        declared.add(key)
        rows.append(dict(_who(customer_uid, cs), direction="ENTERED", basis="DECLARATION",
                         on=_day(npl.get("declared_on")), **{"from": None}, to="NPL", by=npl.get("declared_by"),
                         reason=None, npl_uid=npl.get("uid")))
    notes = [_note("EVENT_LOG_FROM_SYSTEM_START"), _note("NO_NPL_EXIT_RECORD")]
    both = len(declared & changed_in)
    if both:
        notes.append(_note("DECLARATION_ALSO_STATUS_CHANGE", n=both))
    if not rows:
        notes.append(_note("NO_NPL_MOVEMENT_IN_PERIOD"))
    return dict(_definition("npl_movement"),
                period={"start": str(period_start), "end": str(period_end)},
                entered={"by_status_change": by_change_in, "by_declaration": by_declaration, "customers": len(entered)},
                left={"by_status_change": by_change_out, "customers": len(left)},
                rows=rows, empty=not rows, notes=notes)


def _blank_lines():
    return {line: Decimal("0") for line in ARREARS_LINES}


def _served_lines(sums, customers):
    out = {line: _money(sums[line]) for line in ARREARS_LINES}
    out["total"] = _money(sum(sums.values(), Decimal("0")))
    out["customers"] = customers
    return out


def arrears_split(business_date, items, cs, jstate, od02_receipt_customers):
    """True arrears vs arrears held on the company side, per line, over the customers in
    collection (the portfolio's own unit). Only customers with arrears above zero are
    counted; `total` equals the sum of the items' aggregate_overdue."""
    from . import main
    open_case_issue = {i["customer_uid"] for i in cs.issues.values() if i.get("status") == "OPEN"}
    sums = {"true": _blank_lines(), "held": _blank_lines()}
    counts = {"true": 0, "held": 0}
    held_by = {"od02_allocation": 0, "service_issue": 0}
    held_rows = []
    for item in items:
        customer = journey.customer_by_uid(item["customer"]["uid"])
        if customer is None:
            continue
        lines = _blank_lines()
        for contract in customer.contracts:
            lines[LINE_OF_ENTITY.get(contract.entity, "unrouted")] += main._contract_view(contract)[3].cumulative_arrears
        if sum(lines.values(), Decimal("0")) <= 0:
            continue
        case = cs.cases.get(customer.uid) or {}
        reasons = []
        if customer.uid in od02_receipt_customers:
            reasons.append("OD02_RECEIPT_IN_PERIOD")
        if case.get("allocation_hold"):
            reasons.append("OD02_CASE_HOLD")
        if customer.uid in open_case_issue:
            reasons.append("SERVICE_ISSUE_CASE")
        if journey.open_issue_for(jstate, customer.uid):
            reasons.append("SERVICE_ISSUE_JOURNEY")
        side = "held" if reasons else "true"
        counts[side] += 1
        for line in ARREARS_LINES:
            sums[side][line] += lines[line]
        if reasons:
            held_by["od02_allocation"] += any(r.startswith("OD02_") for r in reasons)
            held_by["service_issue"] += any(r.startswith("SERVICE_ISSUE_") for r in reasons)
            row = dict(_who(customer.uid, cs), reasons=reasons)
            row.update({line: _money(lines[line]) for line in ARREARS_LINES})
            row["total"] = _money(sum(lines.values(), Decimal("0")))
            held_rows.append(row)
    held_rows.sort(key=lambda r: (-Decimal(r["total"]), r["customer_uid"]))
    total = {line: sums["true"][line] + sums["held"][line] for line in ARREARS_LINES}
    notes = []
    if not (counts["true"] or counts["held"]):
        notes.append(_note("NO_ARREARS"))
    if held_by["od02_allocation"]:
        notes.append(_note("OD02_OPEN", n=held_by["od02_allocation"]))
    if held_by["service_issue"]:
        notes.append(_note("TWO_ISSUE_REGISTERS"))
    return dict(_definition("arrears_split"), as_of=str(business_date),
                unit="customers in collection with arrears above zero, on the business date",
                unit_th="นับลูกค้าที่อยู่ในการติดตามและมียอดค้างมากกว่า 0 ณ วันทำการ",
                true=_served_lines(sums["true"], counts["true"]),
                held=_served_lines(sums["held"], counts["held"]),
                total=_served_lines(total, counts["true"] + counts["held"]),
                held_by=held_by, held_rows=held_rows, pending_decision="OD-02",
                # Held arrears under OD-02 still carry money already received.
                indicative=bool(held_by["od02_allocation"]),
                empty=not (counts["true"] or counts["held"]), notes=notes)


def status_changes(period_start, period_end, cs):
    rows = []
    for e, customer_uid in reversed(_status_events_in(cs, period_start, period_end)):
        rows.append(dict(_who(customer_uid, cs), case_uid=e.get("case_uid"), on=_day(e.get("on")),
                         **{"from": e.get("from")}, to=e.get("code"), system=e.get("system"), by=e.get("by"),
                         by_system=e.get("by") == "SYSTEM", reason=e.get("reason"), ended=e.get("ended")))
    by_system = sum(1 for r in rows if r["by_system"])
    notes = [_note("EVENT_LOG_FROM_SYSTEM_START")]
    if not rows:
        notes.append(_note("NO_STATUS_CHANGES_IN_PERIOD"))
    return dict(_definition("status_changes"),
                period={"start": str(period_start), "end": str(period_end)},
                rows=rows, order="newest first", count=len(rows), by_system=by_system,
                by_person=len(rows) - by_system, empty=not rows, notes=notes)


def build(business_date, period_start, period_end, items, cs, jstate, od02_receipt_customers):
    """The five blocks, keyed as reports.weekly() serves them."""
    receipts = list(jstate.receipts.values())
    return {
        "mom": mom(business_date, receipts),
        "paying_customers": paying_customers(period_start, period_end, receipts),
        "npl_movement": npl_movement(period_start, period_end, cs, jstate),
        "arrears_split": arrears_split(business_date, items, cs, jstate, od02_receipt_customers),
        "status_changes": status_changes(period_start, period_end, cs),
    }
```

Run the file again before wiring:
```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest tests/test_weekly_figures.py
```
Expected (measured): `16 failed, 1 passed`. Only `test_the_month_spans_stop_on_the_same_day_and_clip_to_a_short_month` passes; the other 16 fail because `reports.weekly()` does not serve the five keys yet. Most fail with a `KeyError` on the key; the snapshot test fails with an `AssertionError`.

- [ ] **Step 5: Wire it into `reports.weekly()`** (`backend/app/reports.py`, exact diff against `caddc4b`; the file is byte-identical at `b5bdc7c`)

```diff
--- a/backend/app/reports.py
+++ b/backend/app/reports.py
@@ -8,6 +8,7 @@
 from . import clock
 from . import journey
 from . import today as today_domain
+from . import weekly_figures
 from .config import settings
 from .session import Store
 
@@ -252,6 +253,12 @@
         "next_week_focus": FOCUS.get(period),
         "counts_by_tier": data["meta"]["counts_by_tier"],
         "reconciliation": reconciliation(),
+        # Feedback Round 1, WP12 (design F15): five figures this payload never served —
+        # additive keys, each with its definition line and its notes. `hold_customers`
+        # is passed, not recomputed, so arrears_split's OD-02 hold names the same
+        # customers as portfolio.allocation_hold_customers.
+        **weekly_figures.build(bd, date.fromisoformat(start), date.fromisoformat(end),
+                               items, cs, jstate, hold_customers),
     }
```

`date` is already imported at `reports.py:4` (`from datetime import date, datetime, timedelta`). There is no import cycle: `weekly_figures` imports only `journey` at module level, and `main` inside `arrears_split`, the way `journey.py` and `cases.py` already reach `main`.

- [ ] **Step 6: Run the focused tests, the payload's other readers, then the suite**

Run:
```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest tests/test_weekly_figures.py
```
Expected: `17 passed`.

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest tests/test_weekly_figures.py tests/test_round1_p3.py tests/test_round2.py tests/test_round3.py tests/test_round4.py tests/test_round5_kpi.py tests/test_today_and_pipeline.py tests/test_audit_coverage.py tests/test_auth_http.py tests/test_payment_status_adjust.py
```
Expected: `220 passed` (measured on scratch copies of both `caddc4b` and `b5bdc7c` with this task applied). A different count means one of those files moved since `caddc4b`; compare it against the same command run before Step 2, not against 220.

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest 2>&1 | tail -1
```
Expected: the Step 1 baseline **+17 passed**, with skips unchanged (from `caddc4b` that would read `1039 passed, 11 skipped`). **Paste the line.**

The frontend and e2e are not run in this task, because no file under `frontend/` or `scripts/` changes. Round B's close (B15) runs `scripts/verify_all.sh`. Prove the claim:
```bash
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 status --short -- backend/app/reports.py backend/app/weekly_figures.py backend/tests/test_weekly_figures.py
```
Expected: exactly ` M backend/app/reports.py`, `?? backend/app/weekly_figures.py` and `?? backend/tests/test_weekly_figures.py`.

- [ ] **Step 7: Read the served payload once, as a person would**

Run:
```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && env -u DATABASE_URL .venv/bin/python -c "
from app import reports
w = reports.weekly()
for k in ('mom', 'paying_customers', 'npl_movement', 'arrears_split', 'status_changes'):
    print(k, [n['code'] for n in w[k]['notes']])
print(w['arrears_split']['true']['total'], w['arrears_split']['held']['total'], w['npl_movement']['entered'])
"
```
Expected (measured on the fixture book):
```
mom ['NO_RECEIPTS_IN_SPAN', 'NO_BASE_FOR_PERCENT', 'NO_PEAK_REPORT']
paying_customers ['NO_RECEIPTS_IN_SPAN', 'NO_RECEIPTS_IN_SPAN', 'NO_BASE_FOR_PERCENT']
npl_movement ['EVENT_LOG_FROM_SYSTEM_START', 'NO_NPL_EXIT_RECORD']
arrears_split ['TWO_ISSUE_REGISTERS']
status_changes ['EVENT_LOG_FROM_SYSTEM_START', 'NO_STATUS_CHANGES_IN_PERIOD']
9076245.88 5580.00 {'by_status_change': 0, 'by_declaration': 1, 'customers': 1}
```
`env -u DATABASE_URL` keeps this read on the fixture book. It never touches `volt_local`.

- [ ] **Step 8: Commit** (message file plus pathspec)

Write `/private/tmp/claude-502/-Users-parattakorn-volt-debt-prototype/205a91ba-9da2-4067-9ec8-d2f683e4a721/scratchpad/rounds-bc/P4/b13-commit-msg.txt`:
```
feat(reports): the weekly report serves month-on-month cash, paying customers, NPL in and out, true vs held arrears, and every status change

Feedback Round 1, WP12 (design F15). Five additive keys on GET /v1/reports/weekly,
computed once in app/weekly_figures.py: mom, paying_customers, npl_movement,
arrears_split, status_changes. Each carries its definition line in Thai and English,
the stores it reads, and coded notes that say when a zero has nothing recorded
behind it or a figure is partial (no PEAK report applied, or one older than the
month; money held under OD-02). Money is Decimal, served as strings; every total,
change and percentage is on the wire.

No key served before changes, no pinned test moves, no screen changes. B14 renders
the five once the weekly overview is committed to design-team.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

Run:
```bash
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 add -- backend/app/weekly_figures.py backend/tests/test_weekly_figures.py backend/app/reports.py
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 commit -F /private/tmp/claude-502/-Users-parattakorn-volt-debt-prototype/205a91ba-9da2-4067-9ec8-d2f683e4a721/scratchpad/rounds-bc/P4/b13-commit-msg.txt -- backend/app/weekly_figures.py backend/tests/test_weekly_figures.py backend/app/reports.py
git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 show --stat HEAD
```
Expected: three files. `backend/app/reports.py` shows 7 insertions; the other two are new files of 447 and 294 lines.

---

### Task B14: The weekly overview and its Excel export show the served figures — **BLOCKED**

**Status: BLOCKED. Write no steps, and read, copy or plan against nothing until every condition below holds.**

**Unblock condition (all three, checked with these commands):**
1. The weekly overview is committed to `design-team`:
   ```bash
   git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 log --oneline design-team -- frontend/src/components/WeeklyOverview.jsx backend/app/weekly_export.py
   ```
   It must list a commit that **adds both paths**: the other session's weekly overview and its Excel export. The commit must name its author (design F18: "say whose commit it is").
2. `feedback-r1` contains that commit, rebased or merged by the shared-branch rule in note 11:
   ```bash
   git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 merge-base --is-ancestor <that-commit> HEAD && echo contained
   ```
   It prints `contained`, and both paths exist in the worktree at HEAD.
3. B13 is committed on `feedback-r1`:
   ```bash
   git -C /Users/parattakorn/volt-debt-worktrees/feedback-r1 log --oneline -- backend/app/weekly_figures.py
   ```
   It is not empty.

**When unblocked, a planner re-cuts B14 to steps.** That planner reads the committed files first, which is allowed once they are on this branch. The task will then do the following.

- **The overview shows the served figures.** In `frontend/src/components/WeeklyOverview.jsx`, each dashed "not sent by the API yet" card for MoM, paying customers, NPL in/out and true-vs-held becomes a figure card **when its key is present on the payload**.
  - The card prints the served strings verbatim. It does no client arithmetic (`api.js:1-4`): the change, the percentage, the totals and the customer counts are all served.
  - It shows `definition_th` or `definition` by the reader's language.
  - It shows every `notes[].th` / `notes[].en`.
  - It badges the figure as indicative when `indicative` is true.
- **A payload without the key keeps the "not sent" card.** This covers a snapshot or edition frozen before B13.
- **The movements table reads `status_changes.rows`** (from → to, by, reason, with the system's changes labelled) instead of `npl_changes`. `npl_movement.rows` backs the NPL card's detail, and `arrears_split.held_rows` backs the held side.
- **The Excel export writes the same figures.** `backend/app/weekly_export.py` writes the same served strings into the cells the overview shows, each figure with its definition line. The writer does no sums.
- **Labels.** `frontend/src/i18n-admin.js` gains only chrome labels (card titles, badge, column heads) under the overview's existing key prefix. Each new key is grepped across all four i18n tables first. The definition sentences and notes come from the server and are not duplicated into i18n.
- **Tests.** Append to the overview's committed test file and to the export's backend test.

**Pins to price at that time (measured then, not now):**
- The committed overview tests that pin "not sent" on the four cards. The intended cost is **0**: if their mocked payloads do not carry the five new keys, the absent-key rule keeps every "not sent" assertion true. Any assertion that must still move is spent as a numbered edit from 36–39, with its measured number and the comment the test contract requires.
- The export's cell-layout test, if one pins the four placeholder cells.
- Density: no census covers `/reports` today (`density.test.jsx` covers the case page, `today-density.test.jsx` covers Today). Confirm by grep when unblocked and record 0, or measure if a census has been added by then.

---

### Self-review (P4)

**Spec coverage — design §3 WP12, line by line**

| WP12 row / sentence | Where | Proof |
|---|---|---|
| **MoM ค่างวด / เงินสด** — this calendar month's receipts vs the same span of last month, SPV vs EPC, from `jstate.receipts` including WP1's PEAK receipts | B13 `mom` | `test_the_month_spans_…`, `test_at_seed_this_month_is_an_empty_span_…`, `test_mom_splits_spv_from_epc_…`, `test_a_peak_receipt_counts_…` |
| **ลูกค้าที่จ่ายสัปดาห์นี้ · WoW** — distinct customers with a receipt in the 7-day period vs the prior 7 days | B13 `paying_customers` | `test_paying_customers_count_each_customer_once_…`, `test_with_no_receipt_in_either_week_…`, `test_with_no_receipt_on_record_at_all_…` |
| **เข้า NPL / ออกจาก NPL** — `PAYMENT_STATUS_SET` into/out of NPL in the period, plus declarations opened in the period; both counted, the note says which | B13 `npl_movement` (`entered.by_status_change`, `entered.by_declaration`, `entered.customers`, `DECLARATION_ALSO_STATUS_CHANGE`) | `test_at_seed_the_one_declaration_…`, `test_a_declaration_counts_twice_by_basis_…` |
| **หนี้ค้างจริง vs พักไว้ฝั่งบริษัท** — OD-02 hold or open service issue = held; the rest = true; per instalment/cash line; sources `_allocation_hold_in_period`, issues | B13 `arrears_split` | `test_the_split_reconciles_…`, `test_an_od02_hold_and_an_open_issue_…`, `test_a_receipt_in_the_period_on_a_late_case_…` |
| **การเปลี่ยนกลุ่ม Late/NPL** — every `PAYMENT_STATUS_SET` in the period (from → to, by, reason), not only `NPL_TYPE_SET` | B13 `status_changes` (`npl_changes` left untouched) | `test_every_payment_status_change_…`, `test_a_status_the_system_followed_…`, `test_with_no_change_in_the_period_…` |
| "each with its definition line in Thai on the card" | B13 serves `definition_th` and `definition`; B14 renders them | `test_the_five_figures_are_served_beside_every_key_served_before` |
| "Definitions are F15" | F15 (a) ruled: the definitions are the WP12 table's, verbatim in `DEFINITIONS` | — |
| "The Excel export writes the same figures" | B14 (blocked, by the controller's ruling) | — |
| Brief: computed once, server-side, Decimal, the client never adds | B13: every total, change and percentage is served as a string; nothing is left to add | the tests assert served strings |
| Brief: say when a source is empty or indicative; never a silent 0 | B13 `notes` codes plus `empty` / `indicative` | the empty-state and PEAK tests |
| Brief: a figure not honestly computable is served "not measurable" | Nothing needed that state, and here is the measured reason. Receipts carry real dates, so both spans are measurable. The event log has every change from the session's start, and WP12 asks for no prior-week NPL comparison. What the log cannot see (changes made before the system, on the sheet) is served as `EVENT_LOG_FROM_SYSTEM_START` on both event-backed figures, and a declaration's exit, which has no record, as `NO_NPL_EXIT_RECORD`. | `test_at_seed_the_one_declaration_…` asserts both codes |

**Placeholder scan.** There is no TBD, no "add validation", and no "similar to Task N". `<task-db>` is deliberate: the controller assigns the database (brief). B14 has no steps **by ruling**. Its header names the exact unblock commands and what it will do.

**Name consistency with what B13 consumes (checked against `caddc4b`)**
- **Router and domain:**
  - `reports.weekly(business_date=None)`, `_period` → strings, `hold_customers` (`reports.py:179`)
  - `today.build()` (`today.py:186`)
  - `journey.contract_by_uid`, `customer_by_uid`, `book_customers`, `open_issue_for(state, customer_uid)`, `make_receipt(state, contract_uid, entity, amount, received_on, invoice_uid=None, matched=…)`, `reset()`
  - `main._contract_view(contract)` → `(contract, dpd, band, block, period)`, with `block.cumulative_arrears`
- **Cases:** `cases.for_current`, `set_allocation_hold(case, arrears)`, `case_arrears(case)`, `log_contact(state, case, fields, by)` → `(row, ptp, issue)`, `contract_field_of`
- **Event keys:** `from`, `code`, `system`, `by`, `reason`, `on`, `ended`
- **Routes:** `POST /v1/cases/{uid}:advance` (journey case uid), `POST /v1/cases/by-customer/{customer_uid}/payment-status` (`{"code", "reason"}`, signed by `X-Volt-Officer`), `POST /v1/reports/weekly:snapshot` (MANAGER/OWNER)
- **Test helpers:** the `SHEET` PAST_DUE LEASE selection copies Round A's ruling for `_with_peak`.
- **Keys:** note 11's key names are kept.

**Assumptions I could not verify in the code (each is a reading of F15, and the served shape lets a different ruling change a rule without a new key):**
1. **"The same span of last month"** is read as day 1 to the same day number, clipped to the shorter month (31 Mar → 1–28 Feb). The design gives no rule for a 31st.
2. **"SPV vs EPC"** uses `cash_in`'s existing keys: `instalment` = SPV, `cash_or_project` = EPC. EPC includes month-37 service fees, exactly as `cash_in` already counts them. The definition line says so.
3. **"Under an OD-02 allocation hold"** is read as either of two things, served as separate reason codes:
   - an unallocated receipt in the period on a LATE/NPL case (`_allocation_hold_in_period`, the design's named source), or
   - the case's standing `allocation_hold` flag, which a KEPT PTP sets even with no receipt.
4. **"An open service issue"** is read as either register (`cs.issues` OPEN, or `jstate.issues` not RESOLVED), served as separate reason codes. The two registers' disagreement about the DPD clock (register divergence #2) is not settled here.
5. **"Held" and "true"** count only in-collection customers with arrears above 0. A held customer with 0 arrears adds nothing and is not listed.
6. **`mom.indicative`** is true whenever no PEAK report is applied or the report predates the business date. On the fixture path it is therefore always true (measured). This is honest for the prototype, but a reader may want the badge only when PEAK receipts exist.
7. **`peak_report_as_of`** is read from the process-wide book (`customer.sheet["peak"]`), as `payment_position` reads it. A session that has not reseeded since another tester's apply can hold PEAK receipts older than that date. This is Round A's known per-session reseed gap, and it is not fixed here.
8. **The event log** is per session and starts empty at seed. Every event's `on` is the fixed business date, so changes before the session are invisible, which the `EVENT_LOG_FROM_SYSTEM_START` note says. Whether a deployed session's log survives a deploy follows `session.Store`; this was not measured.
9. **The first-touch pitfall** (a declaration that first creates the case store writes no event) is real and pre-existing. The tests avoid it; the product is not changed. That a real session always opens a screen that touches the case store before declaring is assumed, not measured, for API-only clients.
10. **The full backend suite with B13** was not run by the planner: no Postgres database is assigned to a planner, and other agents were using the worktree. The DB-free readers of the payload (220 tests) were run on scratch copies of `caddc4b` and `b5bdc7c` with B13 applied.
11. **B14.** That session's test file names, whether its mocks carry the new keys, and its export's cell layout are unknown **by ruling**. The 0-edit expectation in B14's pins is unverified until unblock.
12. **HEAD moved during planning**, from `caddc4b` to `b5bdc7c` (Round A fixes), and an uncommitted `attachments/guard.py` edit remained. B13's files are unaffected (verified by byte comparison and a rerun), but the brief's backend baseline no longer describes HEAD.


<!-- ===== cluster section: P5-roundc.md ===== -->

# Round C — extras: WP5 (PEAK API door, port only) and WP6 (Calendar)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Planner:** P5. Written 2026-09-15 against `feedback-r1`. The work began at `caddc4b`; five Round A fix commits then landed (HEAD `298ad43`), rewriting `PeakReportCard.jsx`, and C1b is re-anchored on that. Design authority: vault note 10 §3 WP5 and WP6, rulings F16, F17 and F19.

**Verified before handing over.** Every backend and frontend code block in this plan was applied to a scratch copy of the tree (`scratchpad/rounds-bc/P5/sim`, never the worktree), with a stand-in for B1's `Reminders.jsx`.
- Backend: **1,081 passed / 11 skipped**, which is the 298ad43 baseline of 1,046 plus the 35 tests added here.
- Frontend: **771 tests / 70 files**, which is 741 / 63 at 298ad43, plus 1 B1 stand-in test, plus the 29 tests added here. `vite build` ok.
- The only pin that failed was the one priced below: `Shell.test.jsx`, 2 tests on 3 literals.

**Tasks:** C1a, C1b (WP5) · C2a, C2b, C2c (WP6 backend) · C3a, C3b, C3c (WP6 screen) · C4 (Round C closes).

**Order:** C1a → C1b. C2a → (C2b, C2c in either order) → C3a (needs B1 as well) → C3b (needs C2c) → C3c (needs C2b) → C4. C1 and C2 touch disjoint files, so they can run in parallel.

## Global constraints (every task carries these)

- **Baseline to beat:** the brief gives caddc4b as backend 1,022 passed / 11 skipped, frontend 726 passed / 63 files, e2e 31 of 31. Measured on 2026-09-15 at 298ad43 in a scratch copy: backend **1,046 passed / 11 skipped**, frontend **741 tests / 63 files**. In the live worktree at 15:30 the frontend showed 11 failures, all from another session's uncommitted `PeakReportCard.jsx` edit. Round C starts from the counts **B15 records when Round B closes**. Each task says how many tests it adds.
- **Test contract:** a pinned (pre-existing) test changes only as a numbered edit 36–39, measured first, with the comment `AUTHORISED TEST EDIT <n> (Feedback Round 1 plan, Arina's approval 2026-09-15): <old> → <new>. <reason>`. Adding tests is free. Edit 17 stays reserved.
- **Density ratchets:** `density.test.jsx` caps the case page at 109 / 128. `today-density.test.jsx` caps Today at 31 / 112 / 1,662 (or whatever B4 recorded). No Round C task touches either screen. No census covers Data sources or the new Calendar. Every screen task still runs both density files to show they did not move.
- `frontend/src/api.js:1-4`: the client never computes a number the server owns, sums across served rows included.
- REQ-COL-075: `payment_status` keeps five values, `payment_status` and `dc_status` stay two fields, `StatusPair` is not modified. Round C reads neither field.
- **PKD-001:** `backend/app/integrations/peak.py` keeps exactly four public functions and stays DRAFT_ONLY. C1 adds a NEW module and never imports or edits `peak.py`.
- **Raw-body uploads only:** no `UploadFile`, because `python-multipart` is not installed.
- **Honesty:**
  - A configured-but-unreachable dependency refuses; an unconfigured one is labelled.
  - Every refusal is an RFC 9457 problem with `message_th`. `problem_from(exc)` in `routers/today.py` fills `errors[0]` only when the CaseError carries `pointer=`.
  - Indicative figures are badged.
  - An unknown query value is a 422, never ignored.
- **PDPA:**
  - Phone numbers live only in their `records` table.
  - E-mail addresses appear only in the user table and the audit subject.
  - The PEAK 13-digit id is never stored.
  - `AUTH_MODE` is never written to `backend/.env`. Test-account passwords are never printed.
  - Round C adds: a notice's title and text never go into audit detail. The PEAK token's value never appears in a response, a log or a test's output.
- **Writes:** role-gated where the design names a role, and audited with `audit.describe(act=…, subject=…, detail=…)` before any side effect that can raise. Sign with `who(body, x_volt_officer)`. `officers.sign` returns a TUPLE.
- **Strings** go in `frontend/src/i18n-*.js` (two flat objects per file), never `prefs.jsx` `DICT`. Every new key was grepped across all four tables on 2026-09-15: `peak.door`, `cal.`, `nav.calendar` and `notice.` returned 0 hits.
- **Python 3.9-safe.**
- **CSS:** only real tokens (`--ink-*`, `--line-default`, `--line-strong`, `--surface-50/100`, `--status-overdue`, `--caption-12`, `--label-13`, `--body-strong-14`), literal px, no hex.
- **Frontend patterns:**
  - `SearchSelect` gets `className="ops-field" labelClassName="ops-field__label" triggerClassName="ops-select"`.
  - Every async effect has an `alive`/`mountedRef` guard.
  - Every `vi.mock('../api.js')` binding called at mount returns a Promise.
  - `rerender` re-wraps `PrefsProvider`.
  - Set the role with `setRole` from `components/role.jsx`.
  - Mount `CaseContactDrawer` with `key={item.customer.uid}`.
- **Worktree rules:**
  - Python is `backend/.venv/bin/python`. Run pytest with `-v`; `pytest.ini` already adds `-q`, so never add it again.
  - Set `VOLT_TEST_PG_URL=postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data`. The controller assigns `<task-db>`.
  - Never set `DATABASE_URL` to `volt_local`. Never run a bare `git stash`. Never cd into `/Users/parattakorn/volt-debt-prototype`.
  - Commit with `git add <new paths>` then `git commit -F <msgfile> -- <paths>`. The message file lives at `"$(git rev-parse --git-dir)/<task>.msg"` and ends with the two trailer lines below. Never `git add -A`.

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
```

## Shared files: every touch, measured at caddc4b and re-checked at 298ad43 (only PeakReportCard.jsx and its test, i18n-admin.js, journey.py and routers/journey.py moved)

| File | Owner of the other touches | Round C touch |
|---|---|---|
| `backend/app/schema.sql` | P2 (B6 `records.customer_contact`), P3 (B8/B10) | **C2b** appends one `records.notice` block at the END of the file, after whatever P2/P3 appended. No existing statement changes. |
| `backend/app/cases.py` | P2 (B6 `set_phone`) | **none.** C2c calls `cases.set_next_action(state, case, action, on, by, note)` (cases.py:924) unchanged; C2a reads `cs.cases/ptps/reviews/issues` and calls `detect_broken_ptps` (:1336) and `reminder_offsets` (:654). |
| `backend/app/routers/today.py` | P1 (B2 filters), P2 (B6 phone route), P3 (B12) | **none.** C2a/C2c import `reminders` (:155-198), `who` (:27), `problem_from` (:44), `dictionary_problem` (:102), `_case_or_404` (:635). **C2a's pre-flight re-checks that `reminders(days, officer)` and its row keys survived Round B.** |
| `backend/app/main.py` | — | **C2a** +2 lines in the router block (after :1587 and :1599). |
| `backend/app/routers/peak_pipeline.py` (Round A) | — | **C1a**: imports (:6-16); helpers after `_RUN_FAILURE_VALIDATION_CODES` (:51); +2 lines in `run_report` (:57-59) and `start_report` (:80-82); `GET /doors` after `last_run` (:107). |
| `backend/app/pipelines/peak_service.py` (Round A) | — | **C1a**: one import; `run_api` appended. |
| `backend/.env.example` | — | **C1a**: +4 comment lines, names only. |
| `frontend/src/api.js` | P1–P4 append bindings too | **C1b** +2 lines after `peakLinkRetire` (:325). **C3a** +2, **C3b** +1, **C3c** +3 appended after the LAST binding in the object (`addCaseNote`, :394 at caddc4b). |
| `frontend/src/components/PeakReportCard.jsx` (Round A, still being fixed) | the Round A fix session (5 commits since caddc4b, plus an uncommitted edit at 15:30) | **C1b** at 298ad43: 2 state lines after :33; a third `doorsLeg` in `reload` (:69-107); one mount line after :182; new `PeakApiDoor` before `PeakLinks` (:232). C1b Step 0 refuses to start while the file is dirty. |
| `frontend/src/i18n-admin.js` | P3 (B9/B11) | **C1b** +7 keys at the end of `ADMIN_EN` (before :602) and `ADMIN_TH` (before :1127). |
| `frontend/src/i18n-journey.js` | any Round B task that adds keys to this table (P1 for B1 `nav.*`) | **C3a** `nav.calendar` after `nav.audit` (EN :308, TH :742); **C3a/C3b/C3c** `cal.*` blocks at the end of `JOURNEY_EN` (before :483) and `JOURNEY_TH` (before :912). |
| `frontend/src/App.jsx` | P1 (B1 `/reminders` route + import) | **C3a**: import Calendar; route `/calendar`; B1's `/reminders` route becomes `<Navigate to="/calendar" replace />`; B1's `Reminders` import removed. |
| `frontend/src/components/Shell.jsx` | P1 (B1 rail row under Today) | **C3a**: B1's `/reminders` row in `GROUPS[1].items` (:40-43) becomes the calendar row. |
| `frontend/src/components/NavIcon.jsx` | — | **C3a** +2 lines (a `calendar` glyph). |
| `frontend/src/app.css` | — | **C3a** +1 `@import './calendar.css';` after :24. |
| `frontend/src/screens/Reminders.jsx` | P1 (B1 creates it) | **C3a**: an `embedded` prop that hides only its own page chrome. |
| `frontend/src/components/Shell.test.jsx` | P1 (B1's numbered edit) | **C3a numbered edit**: 3 string literals, measured in C3a Step 1. |
| `frontend/src/screens/Reminders.test.jsx` | P1 (B1 creates it) | **C3a**: measured by running it; any failing line is priced into the same numbered edit. |
| Not touched | | `Today.jsx`, `CustomerCase.jsx`, `CaseContactDrawer.jsx` (consumed only), `routers/journey.py`, `today.css`, `journey.css`, `admin.css`, both density tests. |

## Depends on

- **Round A at caddc4b**: `PeakReportCard.jsx`, `routers/peak_pipeline.py`, `pipelines/peak_service.py` (C1).
- **B1 (P1)**, for C3a only: `frontend/src/screens/Reminders.jsx` mounting Today's reminders block verbatim (`<details data-testid="reminders">`, `data-reminder-day`, `data-reminder`); route `/reminders`; a rail row under Today; `Reminders.test.jsx`; B1's own Shell.test.jsx edit.
- **B2 (P1)**, for C2a: `routers/today.py` `reminders(days, officer)` keeps its signature and row keys. C2a Step 1 greps it.
- **P2/P3 schema blocks**: append order only (C2b).
- **Edits 36–39**: C3a needs one. If Round B has spent all four, C3a is BLOCKED and goes back to the controller.

## Pins found (measured 2026-09-15)

| Pin | Where | Verdict |
|---|---|---|
| PKD-001 reflection | `backend/tests/test_peak_documents.py:23-28` — `inspect.getmembers(peak_client, inspect.isfunction)` filtered by `f.__module__ == peak_client.__name__` (:25), with `peak_client` bound at :8 to `app.integrations.peak`. The FORBIDDEN loop (:27) scans `app.peak_documents` only. | Scans **one module**, not the package, so a sibling `integrations/peak_reports.py` costs **0**. Re-run in C1a (23 passed with test_audit_coverage and test_landing_schema at caddc4b). |
| No route approves a PEAK doc | `backend/tests/test_today_and_pipeline.py:155-158` | New paths hold no "approve": 0 |
| Every act is logged | `backend/tests/test_audit_coverage.py:34-52` (auto-covers new POST/PUT/DELETE); `:57` pins `LOGGED_READS` | GET `/v1/calendar` is not added to `LOGGED_READS`: 0 |
| Schema tables | `backend/tests/test_landing_schema.py:11-24` (a subset check) | 0 |
| PeakReportCard mock | `frontend/src/components/PeakReportCard.test.jsx:11-17` (28 tests at 298ad43) has no `peakReportDoors` | The card guards `typeof api.peakReportDoors === 'function'`; the new tests go in a new file: 0 |
| `api.reminders` / `api.sendReminder` | `frontend/src/api.test.js:17,27` | Both bindings stay: 0 |
| Rail rows | `frontend/src/components/Shell.test.jsx:25-31` (`TH_ORDER`, `ROUTES`), `:67-72` (EN list) | **C3a: 1 numbered edit, 3 literals** (B1's reminders row → the calendar row) |
| B1's screen test | `frontend/src/screens/Reminders.test.jsx` (not on the branch yet) | Measured by running it in C3a; failing lines priced into the same edit (expected 0 if it renders `<Reminders />` directly) |
| Density | `density.test.jsx` 109/128, `today-density.test.jsx` 31/112/1,662 at caddc4b | Not moved by Round C: 0 |

---

## WP5 — PEAK API door, port only

### Task C1a: The port, the service's refusal, the router's door and its state

**Files:**
- Create: `backend/app/integrations/peak_reports.py`
- Modify: `backend/app/pipelines/peak_service.py` (import at :10; `run_api` appended after `run_upload`, :48-65)
- Modify: `backend/app/routers/peak_pipeline.py` (imports :6-16; helpers after :51; `run_report` :54-60; `start_report` :77-82; new route after `last_run` :97-107)
- Modify: `backend/.env.example` (append 4 comment lines after :15)
- Test: `backend/tests/test_peak_api_door.py` (create)

**Interfaces:**
- Consumes: `app.integrations.env(key, default)` (integrations/__init__.py:34); `peak_service.PipelineRefused(problem)` (:21-24) and `KIND` (:12); `runs.latest(kind)`; `errors.integration_not_configured(name, missing)` (errors.py:831), `errors.validation_failed`, `errors.Problem`; `pipelines._manager_only`, `_body` (routers/pipelines.py:31, :39).
- Produces:
  - `peak_reports.REQUIRED_ENV = ("PEAK_REPORT_API_BASE_URL", "PEAK_REPORT_API_TOKEN")`, `INSTANCES = ("EPC", "SPV")`, `VERIFIED_ENDPOINT = None`, `NOT_CONFIGURED_TH`, `UNTESTED_TH`.
  - Exceptions: `PeakReportApiError(code, detail, detail_th, **extra)` with `.problem() -> dict`; `NotConfigured(missing)` (code `integration_not_configured`, `.missing`); `Untested()` (code `integration_untested`).
  - `peak_reports.state() -> {"state": "not_configured"|"untested", "env": [names], "missing_env": [names], "verified_endpoint": None, "webhook": "not_built"}`.
  - `peak_reports.list_invoices(since, instance)` never returns in this build. It raises `since_invalid` / `instance_unknown` / `NotConfigured` / `Untested`.
  - `peak_service.run_api(since=None, instance="EPC")` always raises `PipelineRefused` with the port's problem, or `adapter_missing`. It never calls `runs.start`.
  - `POST /v1/pipelines/peak-report:run` and `:start`: a JSON body `{"source": "api", "since"?, "instance"?}` is door 2. Answers: 403 for a non-Manager; 422 `integration_not_configured` (extensions `missing_env`); 422 `validation_failed` with pointer `/source`, `/since` or `/instance`; 501 `integration_untested` / `adapter_missing` (error_id `DEBT-INT-0501`, extensions `state`). Any other body is the file, exactly as before.
  - `GET /v1/pipelines/peak-report/doors -> {"doors": [{"door": "upload", "state": "ready", "formats": ["xlsx","csv"], "roles": ["MANAGER","OWNER"]}, {"door": "api", "roles": [...], **peak_reports.state()}]}`. C1b consumes it.

**Pins:** PKD-001 `test_peak_documents.py:23-28` reflects only `app.integrations.peak`, so 0. `test_peak_router.py` (18 tests) posts files without a JSON Content-Type, so 0. Density: no screen, so 0.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_api_door.py
"""WP5 — the PEAK API door is a port with an honest state, never a client against a
guessed endpoint (vault note 10 §3 WP5, ruling F19)."""
import inspect

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import peak as pinned_peak
from app.integrations import peak_reports
from app.main import app
from app.pipelines import peak_service, runs

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
NAMES = ["PEAK_REPORT_API_BASE_URL", "PEAK_REPORT_API_TOKEN"]
TOKEN = "t0ken-never-printed"


@pytest.fixture
def unset(monkeypatch):
    monkeypatch.setattr(peak_reports, "env", lambda key, default=None: default)


@pytest.fixture
def configured(monkeypatch):
    values = {"PEAK_REPORT_API_BASE_URL": "https://peak.invalid", "PEAK_REPORT_API_TOKEN": TOKEN}
    monkeypatch.setattr(peak_reports, "env", lambda key, default=None: values.get(key, default))


@pytest.fixture
def no_network(monkeypatch):
    # The real network transport only: TestClient's own transport is not an HTTPTransport.
    def _refuse(*args, **kwargs):
        raise AssertionError("the PEAK report port must not call out before an endpoint is verified")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


def test_unconfigured_the_port_says_not_configured_and_names_only_the_variables(unset):
    assert peak_reports.state() == {"state": "not_configured", "env": NAMES, "missing_env": NAMES,
                                    "verified_endpoint": None, "webhook": "not_built"}
    with pytest.raises(peak_reports.NotConfigured) as err:
        peak_reports.list_invoices("2026-09-01", "EPC")
    assert err.value.missing == NAMES and err.value.code == "integration_not_configured"


def test_configured_but_unverified_the_port_says_untested_and_calls_nothing(configured, no_network):
    s = peak_reports.state()
    assert s["state"] == "untested" and s["missing_env"] == [] and s["verified_endpoint"] is None
    assert TOKEN not in repr(s)
    with pytest.raises(peak_reports.Untested) as err:
        peak_reports.list_invoices("2026-09-01", "SPV")
    assert err.value.code == "integration_untested" and TOKEN not in repr(err.value.problem())


def test_a_bad_argument_is_the_callers_mistake_whatever_the_state(unset):
    with pytest.raises(peak_reports.PeakReportApiError) as err:
        peak_reports.list_invoices("01/09/2026", "EPC")
    assert err.value.code == "since_invalid"
    with pytest.raises(peak_reports.PeakReportApiError) as err:
        peak_reports.list_invoices(None, "ACME")
    assert err.value.code == "instance_unknown"


def test_the_port_is_a_new_module_that_never_touches_the_pinned_one():
    source = inspect.getsource(peak_reports)
    assert "from .peak import" not in source and "import peak\n" not in source and "httpx" not in source
    assert "peak_reports" not in inspect.getsource(pinned_peak)
    forbidden = ("approve", "post_", "update", "delete", "void", "issue")
    for name, _fn in inspect.getmembers(peak_reports, inspect.isfunction):
        assert not any(bad in name.lower() for bad in forbidden), name


def test_run_api_refuses_before_any_run_starts(unset):
    runs.reset()
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api(since="2026-09-01")
    assert err.value.problem["code"] == "integration_not_configured"
    assert err.value.problem["missing_env"] == NAMES
    assert runs.latest(kind=peak_service.KIND) is None


def test_run_api_refuses_as_untested_once_configured(configured, no_network):
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api()
    assert err.value.problem["code"] == "integration_untested"


def test_if_the_port_ever_answers_the_service_still_refuses_until_an_adapter_is_written(monkeypatch):
    monkeypatch.setattr(peak_reports, "list_invoices", lambda since, instance: [{"doc_no": "IVT-1"}])
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api()
    assert err.value.problem["code"] == "adapter_missing"


def test_the_doors_route_serves_both_doors_by_code(unset):
    body = client.get("/v1/pipelines/peak-report/doors").json()
    doors = {d["door"]: d for d in body["doors"]}
    assert doors["upload"]["state"] == "ready"
    assert doors["api"]["state"] == "not_configured" and doors["api"]["missing_env"] == NAMES
    assert doors["api"]["webhook"] == "not_built"


def test_the_api_door_is_manager_only(unset):
    assert client.post("/v1/pipelines/peak-report:run", json={"source": "api"}, headers=OFFICER).status_code == 403
    assert client.post("/v1/pipelines/peak-report:start", json={"source": "api"}, headers=OFFICER).status_code == 403


def test_the_api_door_refuses_with_a_problem_and_starts_nothing_when_unconfigured(unset):
    runs.reset()
    for verb in (":run", ":start"):
        r = client.post("/v1/pipelines/peak-report" + verb, json={"source": "api", "since": "2026-09-01"},
                        headers=MANAGER)
        assert r.status_code == 422, r.json()
        body = r.json()
        assert body["code"] == "integration_not_configured" and body["message_th"]
        assert body["extensions"]["missing_env"] == NAMES
    assert runs.latest(kind=peak_service.KIND) is None


def test_the_api_door_answers_501_untested_once_configured_and_never_echoes_the_token(configured, no_network):
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "api"}, headers=MANAGER)
    assert r.status_code == 501 and r.json()["code"] == "integration_untested"
    assert r.json()["extensions"]["state"] == "untested" and TOKEN not in r.text


def test_a_json_body_that_is_not_the_api_door_is_a_validation_problem(unset):
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "sftp"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/source"
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "api", "since": "yesterday"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "since_invalid"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='postgresql+psycopg://postgres:@/<task-db>?host=/Users/parattakorn/.volt-postgres/data' .venv/bin/python -m pytest tests/test_peak_api_door.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'peak_reports' from 'app.integrations'`.

- [ ] **Step 3: Write the port**

```python
# backend/app/integrations/peak_reports.py
"""The PEAK invoice-report API door — a PORT, not a client (vault note 10 §3 WP5, ruling F19).

Door 1 (Round A) is the uploaded "รายงานใบแจ้งหนี้" export. Door 2 would pull the same
report from PEAK's API. Nobody has verified an endpoint, a payload or an auth scheme
against PEAK's documentation, so this module holds exactly two things:

  - the NAMES of the configuration door 2 will need (values stay in the environment:
    never in code, a response, a problem or a log);
  - an honest answer: `not_configured` while a name is unset, `untested` once both
    are set, because no endpoint has been verified.

list_invoices therefore never returns and never touches the network. When an endpoint
is verified, the adapter is written here against the documented shape and
VERIFIED_ENDPOINT names the document it was verified against — not before.

PKD-001 pins integrations/peak.py (four public functions, DRAFT_ONLY). This module is
separate on purpose, imports nothing from it, and has no write verb. No webhook
receiver exists: a receiver written against a payload nobody has seen is a guess.
"""
from datetime import date

from . import env

REQUIRED_ENV = ("PEAK_REPORT_API_BASE_URL", "PEAK_REPORT_API_TOKEN")
INSTANCES = ("EPC", "SPV")
# None until an endpoint is verified against PEAK's own documentation; then the title
# and version of that document, and list_invoices gains its adapter.
VERIFIED_ENDPOINT = None

NOT_CONFIGURED_TH = "ยังไม่ได้ตั้งค่าการดึงรายงานใบแจ้งหนี้จาก PEAK API — ต้องตั้ง %s"
UNTESTED_TH = ("ตั้งค่า PEAK API แล้ว แต่ยังไม่ได้ตรวจปลายทางกับเอกสาร API ของ PEAK "
               "ระบบจึงยังไม่ดึงข้อมูล — ใช้การอัปโหลดไฟล์รายงานไปก่อน")


class PeakReportApiError(Exception):
    def __init__(self, code, detail, detail_th, **extra):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.detail_th = detail_th
        self.extra = extra

    def problem(self):
        return dict({"code": self.code, "detail": self.detail, "detail_th": self.detail_th}, **self.extra)


class NotConfigured(PeakReportApiError):
    def __init__(self, missing):
        names = ", ".join(missing)
        super().__init__("integration_not_configured", "Set %s to open the PEAK report API door" % names,
                         NOT_CONFIGURED_TH % names, missing_env=list(missing))
        self.missing = list(missing)


class Untested(PeakReportApiError):
    def __init__(self):
        super().__init__("integration_untested",
                         "No PEAK report endpoint has been verified against PEAK's documentation",
                         UNTESTED_TH)


def _missing():
    return [name for name in REQUIRED_ENV if not env(name)]


def state():
    """The door's state, in codes. Names only — no value is ever read into this dict."""
    missing = _missing()
    return {
        "state": "not_configured" if missing else "untested",
        "env": list(REQUIRED_ENV),
        "missing_env": missing,
        "verified_endpoint": VERIFIED_ENDPOINT,
        "webhook": "not_built",
    }


def _check_since(raw):
    if raw in (None, ""):
        return
    text_value = str(raw)
    try:
        if len(text_value) != 10:
            raise ValueError(text_value)
        date.fromisoformat(text_value)
    except ValueError:
        raise PeakReportApiError("since_invalid", "since must be a date (yyyy-mm-dd); got %r" % text_value,
                                 "วันที่เริ่มดึงต้องเป็นวันที่ รูปแบบ ปี-เดือน-วัน")


def list_invoices(since, instance):
    """Invoices PEAK reports since `since` (yyyy-mm-dd or None) for one instance.

    Refuses in every state this build can be in: a bad argument, a missing name, or an
    endpoint nobody has verified. There is deliberately no request here to refuse later."""
    _check_since(since)
    if instance not in INSTANCES:
        raise PeakReportApiError("instance_unknown", "instance is EPC or SPV; got %r" % (instance,),
                                 "instance ต้องเป็น EPC หรือ SPV")
    missing = _missing()
    if missing:
        raise NotConfigured(missing)
    raise Untested()
```

- [ ] **Step 4: The service refuses before any run starts**

`backend/app/pipelines/peak_service.py`: under `from .. import db, journey` (:9) add

```python
from ..integrations import peak_reports
```

and append after `run_upload`:

```python
ADAPTER_MISSING_TH = ("PEAK API ตอบข้อมูลมา แต่ยังไม่มีตัวแปลงข้อมูลที่ตรวจกับเอกสารของ PEAK "
                      "ระบบจึงไม่นำเข้า — ใช้การอัปโหลดไฟล์รายงานไปก่อน")


def run_api(since=None, instance="EPC"):
    """Door 2 (WP5, F19). Asks the port and REFUSES before any run starts — no registry
    entry, no import_run, no landing row — because nothing verified can be pulled yet.

    If the port ever answers (an endpoint verified and an adapter written in
    integrations/peak_reports.py), this still refuses with adapter_missing until the
    mapping from PEAK's documented payload onto peak_report's invoice record is written
    and tested here. Never a pretend run."""
    try:
        peak_reports.list_invoices(since, instance)
    except peak_reports.PeakReportApiError as exc:
        raise PipelineRefused(exc.problem())
    raise PipelineRefused({"code": "adapter_missing",
                           "detail": "The PEAK report API answered, but no adapter maps its payload onto the report record",
                           "detail_th": ADAPTER_MISSING_TH})
```

- [ ] **Step 5: The router's door and the doors route**

`backend/app/routers/peak_pipeline.py`:

1. After `import re` (:6), add `import json`. After the `from ..pipelines import …` line (:15), add `from ..integrations import peak_reports`.
2. Insert after `_RUN_FAILURE_VALIDATION_CODES = ("unreadable", "header_not_found")` (:51):

```python
# WP5 (F19): door 2. Content-Type decides the door, as routers/pipelines.py:1-6 does for
# crm.lead: application/json carries {"source": "api"}; anything else is the file.
_DOOR_POINTERS = {"since_invalid": "/since", "instance_unknown": "/instance"}


def _is_json(request):
    return "application/json" in (request.headers.get("content-type") or "")


def _door_problem(problem):
    code = problem.get("code")
    if code == "integration_not_configured":
        refusal = errors.integration_not_configured("PEAK report API", problem.get("missing_env") or [])
        refusal.message_th = problem.get("detail_th") or refusal.message_th
        return refusal
    if code in _DOOR_POINTERS:
        return errors.validation_failed([{"pointer": _DOOR_POINTERS[code], "code": code,
                                          "message": problem.get("detail"), "message_th": problem.get("detail_th")}])
    # integration_untested / adapter_missing: the door exists and is not open. 501 — never
    # a 200 that pretends a pull happened, never a 502 that blames PEAK for our gap.
    return errors.Problem(code=code or "integration_untested", status=501,
                          title="The PEAK report API door is not open yet",
                          detail=problem.get("detail"),
                          message_th=problem.get("detail_th") or peak_reports.UNTESTED_TH,
                          error_id="DEBT-INT-0501",
                          extensions={"integration": "PEAK report API", "state": peak_reports.state()["state"]})


def _api_door(raw):
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("source") != "api":
        raise errors.validation_failed([{"pointer": "/source", "code": "invalid",
                                         "message": 'source must be "api", or send the report file as the body',
                                         "message_th": "ต้องระบุ source เป็น api หรือส่งไฟล์รายงานมาใน body"}])
    try:
        return peak_service.run_api(since=body.get("since"), instance=body.get("instance") or "EPC")
    except peak_service.PipelineRefused as exc:
        raise _door_problem(exc.problem)
```

3. In `run_report`, replace

```python
    raw = await _body(request)
    _require_body(raw)
    run = peak_service.run_upload(raw, _filename(x_volt_filename))
```

with

```python
    raw = await _body(request)
    if _is_json(request):
        return _api_door(raw)
    _require_body(raw)
    run = peak_service.run_upload(raw, _filename(x_volt_filename))
```

4. In `start_report`, replace

```python
    raw = await _body(request)
    _require_body(raw)
    uid = runs.start(peak_service.KIND)
```

with

```python
    raw = await _body(request)
    if _is_json(request):
        # Door 2 refuses before any run starts (peak_service.run_api), so there is no
        # uid to hand back and nothing to thread: the refusal is the answer.
        return _api_door(raw)
    _require_body(raw)
    uid = runs.start(peak_service.KIND)
```

5. After the `last_run` function (ends :107), add:

```python
@router.get(PREFIX + "/doors")
def doors():
    """WP5 (F19): both doors and their state, in codes the card turns into words."""
    return {"doors": [
        {"door": "upload", "state": "ready", "formats": ["xlsx", "csv"], "roles": ["MANAGER", "OWNER"]},
        dict(peak_reports.state(), door="api", roles=["MANAGER", "OWNER"]),
    ]}
```

6. Append to `backend/.env.example`:

```
# PEAK invoice-report API — door 2 (Feedback Round 1 WP5). Unverified: setting both moves the door from not_configured to untested; nothing is pulled until an endpoint is verified against PEAK's documentation.
# PEAK_REPORT_API_BASE_URL=
# PEAK_REPORT_API_TOKEN=
```

- [ ] **Step 6: Run the focused tests, the pins, then the suite**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_peak_api_door.py tests/test_peak_documents.py tests/test_peak_router.py tests/test_peak_service.py tests/test_today_and_pipeline.py tests/test_audit_coverage.py -v`
Expected: PASS. `test_pkd_001_the_client_has_two_verbs_and_nothing_else` stays green without edits.
Then: `.venv/bin/python -m pytest tests/`. Expected: B15's backend count + 12 passed, same skips. **Paste the count.**

- [ ] **Step 7: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C1a.msg" <<'EOF'
feat(peak): door 2 is a port — the PEAK report API answers not_configured or untested, and a pull refuses before any run starts

Vault note 10 §3 WP5, ruling F19. integrations/peak_reports.py is a new module; integrations/peak.py (PKD-001) is neither imported nor edited. GET /v1/pipelines/peak-report/doors serves both doors' state. No webhook receiver.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add backend/app/integrations/peak_reports.py backend/tests/test_peak_api_door.py
git commit -F "$(git rev-parse --git-dir)/C1a.msg" -- backend/app/integrations/peak_reports.py backend/app/pipelines/peak_service.py backend/app/routers/peak_pipeline.py backend/.env.example backend/tests/test_peak_api_door.py
```

### Task C1b: The Data sources card lists door 2 with its state in words

**Files:**
- Modify: `frontend/src/api.js` (after `peakLinkRetire`, :325)
- Modify: `frontend/src/components/PeakReportCard.jsx`: state after :33; a third leg in `reload` (:69-107); mount after :182; new `PeakApiDoor` before `function PeakLinks` (:232). **Lines measured at 298ad43.** `caddc4b..298ad43` rewrote this file (+266/−62: independent legs, focus fixes), and on 2026-09-15 15:30 another session had an uncommitted edit to it in the worktree.
- Modify: `frontend/src/i18n-admin.js`: last entries of `ADMIN_EN` (before `}` at :602) and `ADMIN_TH` (before `}` at :1127), at 298ad43
- Test: `frontend/src/components/PeakReportCard.doors.test.jsx` (create; a new file, so the Round A mock at `PeakReportCard.test.jsx:11-17` is not touched)

**Interfaces:**
- Consumes: `GET /v1/pipelines/peak-report/doors` (C1a); `Problem` and `fromError` (already imported at :8-9).
- Produces: `api.peakReportDoors()`. Test ids `peak-door-api`, `peak-door-api-state` (with `data-state`), `peak-door-api-missing`, `peak-door-api-webhook`. i18n keys `peak.door.api.title`, `peak.door.api.state.not_configured`, `peak.door.api.state.untested`, `peak.door.api.state.unknown`, `peak.door.api.unserved`, `peak.door.api.missing`, `peak.door.api.noWebhook` (a grep of all four tables found 0 `peak.door` keys).

**Pins:** `PeakReportCard.test.jsx` (28 tests at 298ad43). Its mock has no `peakReportDoors`, and the card skips the read when the binding is not a function: **0**. `DataSourcesMigration.test.jsx:6` and `DataSourcesReceipt.test.jsx:6` mock no `peakReport*` binding, so the card returns before any read: **0**. Density: Data sources has no census; both density files run unchanged: **0**.

- [ ] **Step 0: Pre-flight: the card is not mid-edit by someone else**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1 && git log --oneline -3 && git status --short frontend/src/components/PeakReportCard.jsx && grep -n "const reload = useCallback\|await Promise.allSettled(\[lastRunLeg, linksLeg\])\|const \[linksProblem, setLinksProblem\]\|data-testid=\"peak-manager-only\"\|^function PeakLinks(" frontend/src/components/PeakReportCard.jsx`
Expected: the status line is empty, and the four anchors used in Step 4 exist. If the file shows ` M`, another session is still editing it: STOP and ask the controller. If an anchor moved, re-read the file and apply the same change at the new place.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/PeakReportCard.doors.test.jsx
// WP5 (F19): door 2 — the PEAK API — is listed with its state in words, in both
// languages, with no control that could pretend a pull happened.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from './role.jsx'
import { PeakReportCard } from './PeakReportCard.jsx'

vi.mock('../api.js', () => ({
  api: {
    peakReportStart: vi.fn(), peakReportRun: vi.fn(), peakReportLastRun: vi.fn(),
    peakReportRows: vi.fn(), peakReportApply: vi.fn(), peakLinks: vi.fn(),
    peakLinkConfirm: vi.fn(), peakLinkRetire: vi.fn(), workbook: vi.fn(), peakReportDoors: vi.fn(),
  },
}))

const NAMES = ['PEAK_REPORT_API_BASE_URL', 'PEAK_REPORT_API_TOKEN']
const doors = (apiDoor) => ({ doors: [
  { door: 'upload', state: 'ready', formats: ['xlsx', 'csv'], roles: ['MANAGER', 'OWNER'] },
  { door: 'api', roles: ['MANAGER', 'OWNER'], env: NAMES, verified_endpoint: null, webhook: 'not_built', ...apiDoor },
] })
const Card = () => <MemoryRouter><PeakReportCard /></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  setRole('MANAGER'); setOfficer('settasak')
  api.peakReportLastRun.mockResolvedValue({ staged: null, applied: null, watch: null })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.peakReportDoors.mockResolvedValue(doors({ state: 'not_configured', missing_env: NAMES }))
})

describe('PeakReportCard — door 2, the PEAK API (WP5, F19)', () => {
  it('lists door 2 as not configured, in Thai, naming only the variables to set', async () => {
    renderIn('th', <Card />)
    const door = await screen.findByTestId('peak-door-api')
    const state = within(door).getByTestId('peak-door-api-state')
    expect(state).toHaveAttribute('data-state', 'not_configured')
    expect(state).toHaveTextContent('ยังไม่ได้ตั้งค่า')
    expect(within(door).getByTestId('peak-door-api-missing')).toHaveTextContent('PEAK_REPORT_API_BASE_URL, PEAK_REPORT_API_TOKEN')
    expect(within(door).getByTestId('peak-door-api-webhook')).toHaveTextContent('ไม่มีตัวรับ webhook')
  })

  it('says untested in English once both names are set, and offers no pull button', async () => {
    api.peakReportDoors.mockResolvedValue(doors({ state: 'untested', missing_env: [] }))
    renderIn('en', <Card />)
    const door = await screen.findByTestId('peak-door-api')
    expect(within(door).getByTestId('peak-door-api-state')).toHaveTextContent('Configured but untested')
    expect(within(door).queryByTestId('peak-door-api-missing')).not.toBeInTheDocument()
    expect(within(door).queryByRole('button')).not.toBeInTheDocument()
  })

  it('an Officer reads the same state — reading it is not an act', async () => {
    setRole('OFFICER')
    renderIn('th', <Card />)
    expect(await screen.findByTestId('peak-door-api-state')).toHaveAttribute('data-state', 'not_configured')
  })

  it('a state this screen does not know is printed as unknown, never mapped to the nearest', async () => {
    api.peakReportDoors.mockResolvedValue(doors({ state: 'ready', missing_env: [] }))
    renderIn('th', <Card />)
    expect(await screen.findByTestId('peak-door-api-state')).toHaveTextContent('สถานะ “ready” ไม่ใช่สถานะที่หน้านี้รู้จัก')
  })

  it('a door state that cannot be read renders the refusal in its own block', async () => {
    api.peakReportDoors.mockRejectedValue(Object.assign(new Error('x'), { problem: {
      code: 'internal_error', title: 'x', message_th: 'อ่านสถานะประตูไม่ได้' } }))
    renderIn('th', <Card />)
    const door = await screen.findByTestId('peak-door-api')
    expect(within(door).getByRole('alert')).toHaveTextContent('อ่านสถานะประตูไม่ได้')
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/components/PeakReportCard.doors.test.jsx`
Expected: 5 failed. `Unable to find an element by: [data-testid="peak-door-api"]`.

- [ ] **Step 3: The binding**

`frontend/src/api.js`, after `peakLinkRetire: …,` (:325):

```js
  // Feedback Round 1 / WP5 (F19): both doors and their state, in codes the card words.
  peakReportDoors: () => get('/v1/pipelines/peak-report/doors'),
```

- [ ] **Step 4: The card**

`frontend/src/components/PeakReportCard.jsx`:

1. After `const [linksProblem, setLinksProblem] = useState(null)` (:33):

```jsx
  const [doors, setDoors] = useState(null)          // GET /doors: {doors: [...]} (WP5)
  const [doorsProblem, setDoorsProblem] = useState(null)
```

2. In `reload`, the links read already runs on its own leg (b5bdc7c). Add door 2 as a third leg. Replace

```jsx
    await Promise.allSettled([lastRunLeg, linksLeg])
```

with

```jsx
    // WP5 (F19): door 2's state, on its own leg like the links — a refused read says so
    // in the door's own block and never hides the receipt or the links.
    const doorsLeg = (async () => {
      if (typeof api.peakReportDoors !== 'function') return
      try {
        const served = await api.peakReportDoors()
        if (mountedRef.current) { setDoors(served); setDoorsProblem(null) }
      } catch (e) {
        if (mountedRef.current) { setDoorsProblem(fromError(e)); setDoors(null) }
      }
    })()

    await Promise.allSettled([lastRunLeg, linksLeg, doorsLeg])
```

3. After the closing `)}` of the `isManager ? (…DropZone…) : (…peak-manager-only…)` block (:182), add:

```jsx
      <PeakApiDoor doors={doors} problem={doorsProblem} t={t} />
```

4. Before the comment block that precedes `function PeakLinks(` (:232), add:

```jsx
// WP5 (F19): door 2 — the PEAK API — listed with its state in words, the same honesty
// as a draft that says UNSENT. No button: nothing verified can be pulled yet, and a
// control that can only refuse would be a promise this card cannot keep. Every role
// reads the state; running a pull stays a Manager's act on the server.
const API_DOOR_STATES = ['not_configured', 'untested']

function PeakApiDoor({ doors, problem, t }) {
  if (!doors && !problem) return null
  const door = (doors?.doors || []).find((d) => d.door === 'api') || null
  const missing = Array.isArray(door?.missing_env) ? door.missing_env : []
  return (
    <div className="peak-rows" data-testid="peak-door-api">
      <h3 className="ad-h3">{t('peak.door.api.title')}</h3>
      {problem && <Problem problem={problem} />}
      {!problem && !door && (
        <p className="ad-quiet" data-testid="peak-door-api-state" data-state="unserved">{t('peak.door.api.unserved')}</p>
      )}
      {door && (
        <p data-testid="peak-door-api-state" data-state={String(door.state)}>
          {API_DOOR_STATES.includes(door.state)
            ? t(`peak.door.api.state.${door.state}`)
            : t('peak.door.api.state.unknown', { state: String(door.state) })}
        </p>
      )}
      {door?.state === 'not_configured' && missing.length > 0 && (
        <p className="ad-quiet" data-testid="peak-door-api-missing">{t('peak.door.api.missing', { names: missing.join(', ') })}</p>
      )}
      {door && <p className="ad-quiet" data-testid="peak-door-api-webhook">{t('peak.door.api.noWebhook')}</p>}
    </div>
  )
}
```

5. `frontend/src/i18n-admin.js`: add these as the last entries of `ADMIN_EN`, directly before its closing `}` (:602 at 298ad43):

```js
  // --- Feedback Round 1 / WP5 — door 2, the PEAK API, with its state in words (F19) ---
  'peak.door.api.title': 'Door 2 — pull from the PEAK API',
  'peak.door.api.state.not_configured': 'Not configured — this build pulls nothing from PEAK’s API',
  'peak.door.api.state.untested': 'Configured but untested — no PEAK endpoint has been checked against PEAK’s documentation, so nothing is pulled',
  'peak.door.api.state.unknown': 'State “{state}” is not one this screen knows — nothing is pulled',
  'peak.door.api.unserved': 'The server did not say what state this door is in',
  'peak.door.api.missing': 'Set {names} to move it to “untested”',
  'peak.door.api.noWebhook': 'No webhook receiver is built: nobody has seen the payload PEAK would send. Upload the report (door 1) meanwhile.',
```

Add these as the last entries of `ADMIN_TH`, directly before its closing `}` (:1127 at 298ad43):

```js
  // --- Feedback Round 1 / WP5 — door 2, the PEAK API, with its state in words (F19) ---
  'peak.door.api.title': 'ประตูที่ 2 — ดึงจาก PEAK API',
  'peak.door.api.state.not_configured': 'ยังไม่ได้ตั้งค่า — ระบบนี้ยังไม่ดึงข้อมูลจาก PEAK API',
  'peak.door.api.state.untested': 'ตั้งค่าแล้วแต่ยังไม่ได้ทดสอบ — ยังไม่ได้ตรวจปลายทางกับเอกสาร API ของ PEAK จึงยังไม่ดึงข้อมูล',
  'peak.door.api.state.unknown': 'สถานะ “{state}” ไม่ใช่สถานะที่หน้านี้รู้จัก — ระบบยังไม่ดึงข้อมูล',
  'peak.door.api.unserved': 'เซิร์ฟเวอร์ไม่ได้แจ้งสถานะของประตูนี้',
  'peak.door.api.missing': 'ตั้งค่า {names} เพื่อเปลี่ยนเป็น “ยังไม่ได้ทดสอบ”',
  'peak.door.api.noWebhook': 'ไม่มีตัวรับ webhook: ยังไม่มีใครเห็นรูปแบบข้อมูลที่ PEAK จะส่งมา ระหว่างนี้ให้อัปโหลดไฟล์รายงาน (ประตูที่ 1)',
```

Before saving, re-run `grep -n "'peak\.door" frontend/src/i18n-*.js frontend/src/prefs.jsx`. Expect only the 14 lines you just added, because `i18n.test.js` does not catch a same-table overwrite.

- [ ] **Step 5: Focused tests, pins, density, suite, build**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/components/PeakReportCard.doors.test.jsx src/components/PeakReportCard.test.jsx src/screens/DataSourcesMigration.test.jsx src/screens/DataSourcesReceipt.test.jsx src/i18n.test.js`
Expected: PASS (5 new + 28 unchanged + the rest).
Run: `npx vitest run src/density.test.jsx src/today-density.test.jsx`. Expected census lines unchanged: `PRE-CONTACT+PAY … visible=109`, `WORKED+PAY … visible=128`, `TODAY chrome=112 perRow=31 at 50 rows=1662`, or B4's recorded numbers if Round B moved Today. **Paste them.**
Run: `npx vitest run && npm run build`. Expected: B15's frontend count + 5 tests, + 1 file; build ok. **Paste the count.**

- [ ] **Step 6: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C1b.msg" <<'EOF'
feat(data sources): the PEAK card lists door 2 — the API — with its state in words, and no button that could pretend

Vault note 10 §3 WP5, ruling F19. Reads GET /v1/pipelines/peak-report/doors; an unknown state is printed as unknown; a refused read renders the Problem in the door's own block.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/components/PeakReportCard.doors.test.jsx
git commit -F "$(git rev-parse --git-dir)/C1b.msg" -- frontend/src/api.js frontend/src/components/PeakReportCard.jsx frontend/src/i18n-admin.js frontend/src/components/PeakReportCard.doors.test.jsx
```

---

## WP6 — Calendar

Measured on the seeded book on 2026-09-15 (business date 2026-10-23), with the serializers below run against caddc4b in a scratch probe:
- The default grid (2026-09-28 to 2026-11-08) holds **109 items**:
  - NEXT_ACTION 98, from cases.next_action
  - PTP_DUE 1, from cases.ptp; the journey copy of the same promise was skipped as mirrored
  - REMINDER_BATCH 1 (48 customers, D-3, 2026-11-07)
  - REVIEW_SLA 3 from cases.review and 2 from journey.review
  - RESTRUCTURE 2
  - SETTLEMENT 1 (cash ladder)
  - NPL_BUYBACK 1 (2026-10-14)
- **The busiest day, 2026-10-23, holds 99 items.** The screen must name that number, never cut it silently.
- Case officers per item: 0 missing. Officer `nantapol` owns 20 of the items, plus 39 of the reminder rows.

### Task C2a: `GET /v1/calendar`: one dated list, one serializer per store

**Files:**
- Create: `backend/app/calendar_feed.py`
- Create: `backend/app/routers/calendar.py`
- Modify: `backend/app/main.py`. Add `from .routers.calendar import router as calendar_router  # noqa: E402` after :1587 (the `login_router` import) and `app.include_router(calendar_router)` after :1599.
- Test: `backend/tests/test_calendar.py` (create)

**Interfaces:**
- Consumes:
  - `cases.for_current()` with `.cases`, `.ptps`, `.reviews`, `.issues`; `cases.detect_broken_ptps(state, as_of)`; `cases.reminder_offsets()`.
  - `journey.for_current()` with `.ptps`, `.reviews`, `.issues`, `.restructures`, `.cash_cases`, `.arrangements`, `.npl_cases`, `.cases`; `journey.customer_by_uid`.
  - `routers.today.reminders(days, officer)`, reading rows `customer_uid, display_name, volt_id, due_on, kind, overdue, officer_uid` and `meta.batch_label`.
  - `officers.registry()`, `settings.business_date`, `settings.review_sla_hours`.
- Produces:
  - `calendar_feed`: `MAX_SPAN_DAYS = 42`, `KINDS`, `KIND_RANK`, `NEXT_ACTION_EXCLUDED = ("SEND_REMINDER", "NONE_CLOSED")`, `UNSCOPED_KINDS = ("REMINDER_BATCH", "NOTICE")`.
  - Range and aggregate helpers: `default_range(bd) -> (date, date)`, `not_dated(cs, js)`, `ordered(items)`, `day_totals(items, start, end)`, `count_by(items, key)`.
  - One serializer per store (C2b adds `notices(rows, cs, bd)`):
    - `next_actions(cs, start, end, bd)`
    - `case_ptps(cs, start, end, bd)`
    - `journey_ptps(js, cs, start, end, bd) -> (rows, mirrored_count)`
    - `reminder_batches(rows, start, end, bd, batch_label)`
    - `case_reviews(cs, start, end, bd)`
    - `journey_reviews(js, cs, start, end, bd)`
    - `case_issues(cs, start, end, bd)`
    - `restructures(js, cs, start, end, bd)`
    - `settlements(js, cs, start, end, bd)`
    - `npl_buybacks(js, cs, start, end, bd)`
  - **Item shape:** `{uid, kind, source, on, time, overdue, movable, facts, customer_uid, display_name, volt_id, officer_uid}`.
    - `kind` is one of `KINDS`.
    - `source` is one of `cases.next_action`, `cases.ptp`, `journey.ptp`, `today.reminders`, `cases.review`, `journey.review`, `cases.issue`, `journey.restructure`, `journey.cash_case`, `journey.arrangement`, `journey.npl_case`, or (C2b) `records.notice`.
  - `GET /v1/calendar?from=yyyy-mm-dd&to=yyyy-mm-dd&officer=<uid>` returns `{items, days: [{on, total}] (every day in range), meta: {from, to, defaulted, business_date, max_span_days, officer, total, by_kind, by_source, officers: [{uid, display_name_th}], not_dated: {"cases.issue": n, "journey.issue": n}, journey_ptps_mirrored, next_action_excluded, review_sla_hours}}`.
  - **Refusals** are all 422 `validation_failed`: pointer `/from` or `/to` with `required` (one of the pair given); `date_invalid`; `range_reversed`; `range_too_long` (with `max_days: 42`); `/officer` `value_unknown` (with `known`).
  - No role gate: reading dated work is not an act, the same as `GET /v1/today`.

**Pins:** `test_audit_coverage.py:57` `LOGGED_READS` is unchanged, so 0. No screen, so density 0.

- [ ] **Step 1: Pre-flight: the consumed names survived Round B**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1 && grep -n "^def reminders\|\"due_on\": case\|\"kind\": (\"D-%d\"\|\"officer_uid\": case\[\"officer_uid\"\]\|\"batch_label\":" backend/app/routers/today.py && grep -n "^def set_next_action\|^def detect_broken_ptps\|^def reminder_offsets" backend/app/cases.py`
Expected: `def reminders(days: int = Query(default=21), officer: str = Query(default=None)):` plus the four row/meta keys, and the three cases functions. If `reminders` changed its signature or keys, STOP and report to the controller. Do not adapt silently.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_calendar.py
"""WP6 — one dated list from the stores that already hold dates (vault note 10 §3, F16)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey
from app.config import settings
from app.main import app

BD = settings.business_date
HEAD = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _client():
    # Pinned to the shared session so direct store reads see what the route served
    # (test_audit_enrichment.py's _shared_client does the same).
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _get(c, **params):
    return c.get("/v1/calendar", params=params, headers=HEAD)


def test_with_no_range_it_serves_the_six_week_grid_around_the_business_date_and_says_so():
    body = _get(_client()).json()
    meta = body["meta"]
    assert meta["defaulted"] is True and meta["business_date"] == str(BD) and meta["max_span_days"] == 42
    start, end = date.fromisoformat(meta["from"]), date.fromisoformat(meta["to"])
    assert start.weekday() == 0 and (end - start).days + 1 == 42
    assert start <= BD.replace(day=1) and BD <= end
    assert [d["on"] for d in body["days"]] == [(start + timedelta(days=i)).isoformat() for i in range(42)]


def test_every_item_names_its_store_and_the_served_totals_agree_with_the_items():
    body = _get(_client()).json()
    assert body["items"]
    for item in body["items"]:
        assert item["kind"] and item["source"] and item["on"]
    per_day = {}
    for item in body["items"]:
        per_day[item["on"]] = per_day.get(item["on"], 0) + 1
    assert {d["on"]: d["total"] for d in body["days"] if d["total"]} == per_day
    assert body["meta"]["total"] == len(body["items"]) == sum(d["total"] for d in body["days"])


def test_every_next_action_on_the_business_date_is_served_none_truncated():
    c = _client()
    body = _get(c).json()
    cs = cases_domain.for_current()
    expected = sorted(uid for uid, k in cs.cases.items()
                      if k["next_action_on"] == str(BD) and k["next_action"] not in ("SEND_REMINDER", "NONE_CLOSED"))
    served = sorted(i["customer_uid"] for i in body["items"] if i["kind"] == "NEXT_ACTION" and i["on"] == str(BD))
    assert served == expected and len(served) > 3
    assert all(i["movable"] and i["source"] == "cases.next_action" for i in body["items"] if i["kind"] == "NEXT_ACTION")


def test_a_send_reminder_next_action_is_served_as_a_batch_with_the_reminders_endpoints_own_label():
    c = _client()
    body = _get(c).json()
    batches = [i for i in body["items"] if i["kind"] == "REMINDER_BATCH"]
    rows = c.get("/v1/today/reminders", params={"days": 60}).json()["reminders"]
    in_range = [r for r in rows if body["meta"]["from"] <= r["due_on"] <= body["meta"]["to"]]
    assert sum(b["facts"]["count"] for b in batches) == len(in_range) > 0
    labels = ("D0", "D-%d" % cases_domain.reminder_offsets()[0])
    assert all(b["source"] == "today.reminders" and b["facts"]["label"] in labels for b in batches)
    assert not any(i["kind"] == "NEXT_ACTION" and i["facts"]["action"] == "SEND_REMINDER" for i in body["items"])


def test_an_open_promise_is_served_once_although_both_registers_hold_it():
    body = _get(_client()).json()
    keys = [(i["customer_uid"], i["on"]) for i in body["items"] if i["kind"] == "PTP_DUE"]
    assert len(keys) == len(set(keys))
    open_journey = [p for p in journey.for_current().ptps.values() if p["status"] == "OPEN"
                    and body["meta"]["from"] <= p["promise_date"] <= body["meta"]["to"]]
    assert all((p["customer_uid"], p["promise_date"]) in set(keys) for p in open_journey)
    assert body["meta"]["journey_ptps_mirrored"] >= 1


def test_review_deadlines_come_from_both_registers_and_each_says_how_precise_it_is():
    body = _get(_client()).json()
    reviews = [i for i in body["items"] if i["kind"] == "REVIEW_SLA"]
    assert {i["source"] for i in reviews} == {"cases.review", "journey.review"}
    case_review = next(i for i in reviews if i["source"] == "cases.review")
    assert case_review["facts"]["precision"] == "hour" and case_review["time"]
    assert case_review["facts"]["sla_hours"] == settings.review_sla_hours
    journey_review = next(i for i in reviews if i["source"] == "journey.review")
    assert journey_review["facts"]["precision"] == "day" and journey_review["time"] is None


def test_a_ticket_deadline_is_the_tickets_own_date_and_an_undated_issue_is_counted_not_placed():
    c = _client()
    cs = cases_domain.for_current()
    uid = next(u for u, k in cs.cases.items() if k["payment_status"] == "LATE" and not k["open_issue_uid"])
    issue = cases_domain._make_issue(cs, cs.cases[uid], {"summary": "Inverter fault", "deadline": "2026-10-30",
                                                         "opened_by": "nantapol"})
    body = _get(c).json()
    row = next(i for i in body["items"] if i["kind"] == "ISSUE_DEADLINE" and i["facts"]["issue_uid"] == issue["uid"])
    assert row["on"] == "2026-10-30" and row["source"] == "cases.issue" and row["customer_uid"] == uid
    assert body["meta"]["not_dated"]["journey.issue"] >= 1


def test_restructure_settlement_and_buyback_dates_are_read_from_the_journey_store():
    body = _get(_client(), **{"from": "2026-09-28", "to": "2026-11-08"}).json()
    phases = {(i["kind"], i["facts"].get("phase")) for i in body["items"]}
    assert ("RESTRUCTURE", "PROPOSED") in phases and ("RESTRUCTURE", "FIRST_DUE") in phases
    assert ("SETTLEMENT", "PLAN_OFFERED") in phases
    buyback = next(i for i in body["items"] if i["kind"] == "NPL_BUYBACK")
    assert buyback["on"] == "2026-10-14" and buyback["source"] == "journey.npl_case"
    assert buyback["facts"]["indicative"] is True and buyback["facts"]["amount"]


def test_a_bad_range_is_refused_with_a_pointer_never_ignored():
    c = _client()

    def err(**params):
        r = _get(c, **params)
        assert r.status_code == 422, r.json()
        return r.json()["errors"][0]
    assert err(**{"from": "2026-10-01"})["pointer"] == "/to"
    assert err(**{"from": "01/10/2026", "to": "2026-10-31"})["code"] == "date_invalid"
    assert err(**{"from": "2026-10-31", "to": "2026-10-01"})["code"] == "range_reversed"
    too_long = err(**{"from": "2026-10-01", "to": "2026-11-12"})
    assert too_long["code"] == "range_too_long" and too_long["max_days"] == 42
    assert err(officer="nobody")["code"] == "value_unknown"


def test_the_officer_filter_scopes_every_case_item_to_that_officers_cases():
    body = _get(_client(), officer="nantapol").json()
    assert body["meta"]["officer"] == "nantapol" and body["items"]
    for item in body["items"]:
        if item["kind"] == "REMINDER_BATCH":
            assert all(x["officer_uid"] == "nantapol" for x in item["facts"]["customers"])
        else:
            assert item["officer_uid"] == "nantapol"
    assert {"nantapol", "thip"} <= {o["uid"] for o in body["meta"]["officers"]}


def test_a_week_range_serves_exactly_its_seven_days():
    body = _get(_client(), **{"from": "2026-10-19", "to": "2026-10-25"}).json()
    assert [d["on"] for d in body["days"]][0] == "2026-10-19" and len(body["days"]) == 7
    assert body["meta"]["defaulted"] is False
    assert all("2026-10-19" <= i["on"] <= "2026-10-25" for i in body["items"])
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar.py -v`
Expected: 11 failed, each on `KeyError: 'meta'` or `'items'` (a 404 body from the SPA fallback or `{"detail":"Not Found"}`).

- [ ] **Step 4: The read model**

```python
# backend/app/calendar_feed.py
"""The calendar's read model — vault note 10 §3 WP6 (F16).

One dated list drawn from the stores that already hold dates. Nothing here is a new
fact: each serializer reads ONE store, names it in `source`, and places the item on the
store's own date. A store that holds no date for an open record (a journey service
issue) is counted in not_dated, never given a date.

Two registers of promises and reviews exist (cases.CaseState and journey.JourneyState,
design §7). Both are read and every item names which. A journey promise the case store
already mirrors (cases._seed, source "JOURNEY") is served once, from the case store.
"""
from datetime import date, datetime, timedelta

from . import journey
from .config import settings

MAX_SPAN_DAYS = 42              # a six-week month grid, the largest view the screen draws
KINDS = ("NEXT_ACTION", "PTP_DUE", "REMINDER_BATCH", "REVIEW_SLA", "ISSUE_DEADLINE",
         "RESTRUCTURE", "SETTLEMENT", "NPL_BUYBACK", "NOTICE")
KIND_RANK = {kind: rank for rank, kind in enumerate(KINDS)}
# SEND_REMINDER is served as a REMINDER_BATCH; NONE_CLOSED is not an action at all.
NEXT_ACTION_EXCLUDED = ("SEND_REMINDER", "NONE_CLOSED")
# Kinds the officer filter does not scope: a batch is scoped by the reminders call
# itself, and a notice belongs to its owner, not to a case's officer.
UNSCOPED_KINDS = ("REMINDER_BATCH", "NOTICE")
NOBODY = {"customer_uid": None, "display_name": None, "volt_id": None, "officer_uid": None}


def _day(value):
    """A store's own date as yyyy-mm-dd, or None when it is not a date this can read."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _within(on, start, end):
    return bool(on) and start.isoformat() <= on <= end.isoformat()


def _who(customer_uid, cs):
    if not customer_uid:
        return dict(NOBODY)
    customer = journey.customer_by_uid(customer_uid)
    case = cs.cases.get(customer_uid)
    return {"customer_uid": customer_uid,
            "display_name": getattr(customer, "display_name", None),
            "volt_id": getattr(customer, "volt_id", None),
            "officer_uid": case["officer_uid"] if case else None}


def _item(uid, kind, source, on, who, overdue, time=None, movable=False, facts=None):
    row = {"uid": uid, "kind": kind, "source": source, "on": on, "time": time,
           "overdue": bool(overdue), "movable": movable, "facts": facts or {}}
    row.update(who)
    return row


def default_range(bd):
    first = bd.replace(day=1)
    start = first - timedelta(days=first.weekday())
    return start, start + timedelta(days=MAX_SPAN_DAYS - 1)


def next_actions(cs, start, end, bd):
    """cases.CaseState.cases — the one next action every case carries (REQ-COL-070)."""
    out = []
    for customer_uid, case in cs.cases.items():
        on = _day(case.get("next_action_on"))
        if case.get("next_action") in (None,) + NEXT_ACTION_EXCLUDED or not _within(on, start, end):
            continue
        out.append(_item("na:%s" % customer_uid, "NEXT_ACTION", "cases.next_action", on, _who(customer_uid, cs),
                         on < str(bd), movable=True,
                         facts={"action": case["next_action"], "set_by": case.get("next_action_set_by")}))
    return out


def case_ptps(cs, start, end, bd):
    """cases.CaseState.ptps — open promises, on their promise date."""
    out = []
    for ptp in cs.ptps.values():
        on = _day(ptp.get("promise_date"))
        if ptp.get("status") != "OPEN" or not _within(on, start, end):
            continue
        out.append(_item("ptp:%s" % ptp["uid"], "PTP_DUE", "cases.ptp", on, _who(ptp["customer_uid"], cs),
                         on < str(bd), facts={"ptp_uid": ptp["uid"], "amount": ptp.get("promised_amount"),
                                              "origin": ptp.get("source")}))
    return out


def journey_ptps(js, cs, start, end, bd):
    """journey.JourneyState.ptps — the second register. A promise the case store mirrors
    (same customer, same date, source JOURNEY) is skipped; the count of those comes back."""
    mirrored = {(p["customer_uid"], p["promise_date"]) for p in cs.ptps.values() if p.get("source") == "JOURNEY"}
    out, skipped = [], 0
    for ptp in js.ptps.values():
        on = _day(ptp.get("promise_date"))
        if ptp.get("status") != "OPEN" or not _within(on, start, end):
            continue
        if (ptp["customer_uid"], on) in mirrored:
            skipped += 1
            continue
        out.append(_item("jptp:%s" % ptp["uid"], "PTP_DUE", "journey.ptp", on, _who(ptp["customer_uid"], cs),
                         on < str(bd), facts={"ptp_uid": ptp["uid"], "amount": ptp.get("promised_amount"),
                                              "origin": ptp.get("kind")}))
    return out, skipped


def reminder_batches(rows, start, end, bd, batch_label):
    """GET /v1/today/reminders' own rows (the block WP7 moved off Today), grouped into one
    batch per day and label. The label is that endpoint's own, never re-derived here."""
    groups = {}
    for r in rows:
        on = _day(r.get("due_on"))
        if not _within(on, start, end):
            continue
        groups.setdefault((on, r["kind"]), []).append(
            {"customer_uid": r["customer_uid"], "display_name": r.get("display_name"), "volt_id": r.get("volt_id"),
             "officer_uid": r.get("officer_uid"), "overdue": bool(r.get("overdue"))})
    return [_item("rb:%s:%s" % (on, label), "REMINDER_BATCH", "today.reminders", on, dict(NOBODY), on < str(bd),
                  facts={"label": label, "count": len(customers), "customers": customers, "batch_label": batch_label})
            for (on, label), customers in sorted(groups.items())]


def _sla_days():
    return -(-int(settings.review_sla_hours) // 24)       # whole days, rounded up


def case_reviews(cs, start, end, bd):
    """cases.CaseState.reviews — an open review is due review_sla_hours after
    raised_at_time, the clock GET /v1/reviews measures age_hours by. A review with no
    readable time falls back to its raised_at day, and says precision "day"."""
    hours = int(settings.review_sla_hours)
    out = []
    for review in cs.reviews.values():
        if review.get("status") != "OPEN":
            continue
        try:
            due_at = datetime.fromisoformat(review["raised_at_time"]) + timedelta(hours=hours)
            on, time, precision = due_at.date().isoformat(), due_at.strftime("%H:%M"), "hour"
        except (KeyError, TypeError, ValueError):
            raised = _day(review.get("raised_at"))
            if raised is None:
                continue
            on = (date.fromisoformat(raised) + timedelta(days=_sla_days())).isoformat()
            time, precision = None, "day"
        if not _within(on, start, end):
            continue
        out.append(_item("rv:%s" % review["uid"], "REVIEW_SLA", "cases.review", on, _who(review["customer_uid"], cs),
                         on < str(bd), time=time,
                         facts={"review_uid": review["uid"], "reason": review.get("reason"),
                                "raised_at": review.get("raised_at"), "sla_hours": hours, "precision": precision}))
    return out


def journey_reviews(js, cs, start, end, bd):
    """journey.JourneyState.reviews — the manager-review queue stores a day, not a time,
    so the same review_sla_hours lands on a day: opened_on + the SLA in whole days."""
    out = []
    for review in js.reviews.values():
        opened = _day(review.get("opened_on"))
        if review.get("status") != "OPEN" or opened is None:
            continue
        on = (date.fromisoformat(opened) + timedelta(days=_sla_days())).isoformat()
        if not _within(on, start, end):
            continue
        out.append(_item("mrv:%s" % review["uid"], "REVIEW_SLA", "journey.review", on,
                         _who(review["customer_uid"], cs), on < str(bd),
                         facts={"review_uid": review["uid"], "reason": review.get("reason"), "raised_at": opened,
                                "sla_hours": int(settings.review_sla_hours), "precision": "day"}))
    return out


def case_issues(cs, start, end, bd):
    """cases.CaseState.issues — an open ticket on its OWN deadline (J4-07's field)."""
    out = []
    for issue in cs.issues.values():
        on = _day(issue.get("deadline"))
        if issue.get("status") != "OPEN" or not _within(on, start, end):
            continue
        out.append(_item("iss:%s" % issue["uid"], "ISSUE_DEADLINE", "cases.issue", on, _who(issue["customer_uid"], cs),
                         on < str(bd), facts={"issue_uid": issue["uid"], "responsible_team": issue.get("responsible_team"),
                                              "ticket_ref": issue.get("ticket_ref"), "ticket_url": issue.get("ticket_url"),
                                              "summary": issue.get("summary")}))
    return out


def restructures(js, cs, start, end, bd):
    """journey.JourneyState.restructures — a proposal on the day it was proposed (while it
    is still PROPOSED), and the first due date of the new schedule it names."""
    out = []
    for rst in js.restructures.values():
        who = _who((js.cases.get(rst.get("case_uid")) or {}).get("customer_uid"), cs)
        facts = {"restructure_uid": rst["uid"], "status": rst.get("status"), "new_term_months": rst.get("new_term_months")}
        proposed = _day(rst.get("proposed_on"))
        if rst.get("status") == "PROPOSED" and _within(proposed, start, end):
            out.append(_item("rst:%s:proposed" % rst["uid"], "RESTRUCTURE", "journey.restructure", proposed, who, False,
                             facts=dict(facts, phase="PROPOSED")))
        first_due = _day(rst.get("new_first_due"))
        if rst.get("status") in ("PROPOSED", "ACTIVE") and _within(first_due, start, end):
            out.append(_item("rst:%s:first-due" % rst["uid"], "RESTRUCTURE", "journey.restructure", first_due, who, False,
                             facts=dict(facts, phase="FIRST_DUE")))
    return out


def settlements(js, cs, start, end, bd):
    """journey.JourneyState — a cash settlement plan on the day its ladder recorded the
    offer (stage SETTLEMENT_PLAN_60), and an ACTIVE repayment arrangement on the day it opened."""
    out = []
    for cash in js.cash_cases.values():
        if cash.get("stage") != "SETTLEMENT_PLAN_60":
            continue
        entry = next((h for h in reversed(cash.get("stage_history") or []) if h.get("stage") == "SETTLEMENT_PLAN_60"), None)
        on = _day(entry.get("on")) if entry else None
        if not _within(on, start, end):
            continue
        out.append(_item("cash:%s:settlement" % cash["uid"], "SETTLEMENT", "journey.cash_case", on,
                         _who(cash["customer_uid"], cs), False,
                         facts={"phase": "PLAN_OFFERED", "ref_uid": cash["uid"], "by": entry.get("by")}))
    for arrangement in js.arrangements.values():
        on = _day(arrangement.get("opened_on"))
        if arrangement.get("status") != "ACTIVE" or not _within(on, start, end):
            continue
        out.append(_item("arr:%s" % arrangement["uid"], "SETTLEMENT", "journey.arrangement", on,
                         _who(arrangement["customer_uid"], cs), False,
                         facts={"phase": "ARRANGEMENT_OPENED", "ref_uid": arrangement["uid"], "by": None}))
    return out


def npl_buybacks(js, cs, start, end, bd):
    """journey.JourneyState.npl_cases — the executed deed and buy-back payment (day 120,
    journey.execute_assignment). No store holds a buy-back date before it is executed,
    so none is invented. The amount is 100% of remaining NPV at an undecided discount
    rate (OQ-31): indicative, and served as such."""
    out = []
    for npl in js.npl_cases.values():
        deed = npl.get("assignment") or {}
        on = _day(deed.get("executed_on"))
        if not _within(on, start, end):
            continue
        out.append(_item("npl:%s:buyback" % npl["uid"], "NPL_BUYBACK", "journey.npl_case", on,
                         _who((js.cases.get(npl.get("case_uid")) or {}).get("customer_uid"), cs), False,
                         facts={"npl_uid": npl["uid"], "amount": deed.get("remaining_npv"),
                                "indicative": bool(deed.get("is_indicative", True)), "by": deed.get("by")}))
    return out


def not_dated(cs, js):
    """Open records a store holds with no date the calendar can place — counted, never dated."""
    return {
        "cases.issue": sum(1 for i in cs.issues.values() if i.get("status") == "OPEN" and not _day(i.get("deadline"))),
        "journey.issue": sum(1 for i in js.issues.values() if i.get("status") in ("OPEN", "IN_PROGRESS")),
    }


def ordered(items):
    return sorted(items, key=lambda r: (r["on"], r["time"] or "", KIND_RANK[r["kind"]], r["display_name"] or "", r["uid"]))


def count_by(items, key):
    out = {}
    for row in items:
        out[row[key]] = out.get(row[key], 0) + 1
    return out


def day_totals(items, start, end):
    """Every day in the range with its served total — zero days included, so the screen
    never has to decide that an absent day means none."""
    counts = count_by(items, "on")
    out, day = [], start
    while day <= end:
        out.append({"on": day.isoformat(), "total": counts.get(day.isoformat(), 0)})
        day += timedelta(days=1)
    return out
```

- [ ] **Step 5: The route**

```python
# backend/app/routers/calendar.py
"""The calendar — vault note 10 §3 WP6, ruling F16.

GET /v1/calendar serves one dated list from the stores that already hold dates
(calendar_feed.py names the store on every item). The screen reads it, moves a next
action with a reason (C2c), and keeps personal notices (C2b). No recurrence, no
sharing, no e-mail.
"""
from datetime import date

from fastapi import APIRouter, Query

from .. import calendar_feed, cases as cases_domain, errors, journey, officers
from ..config import settings
from . import today as today_router

router = APIRouter()


def _date_param(raw, pointer):
    try:
        if len(raw) != 10:
            raise ValueError(raw)
        return date.fromisoformat(raw)
    except ValueError:
        raise errors.validation_failed([{
            "pointer": pointer, "code": "date_invalid",
            "message": "%s must be a date (yyyy-mm-dd); got %r" % (pointer[1:], raw),
            "message_th": "วันที่ไม่ถูกต้อง ใช้รูปแบบ ปี-เดือน-วัน"}])


def _range(start_raw, end_raw, bd):
    """Both or neither. Neither is the six-week grid around the business date, and the
    answer says so (meta.defaulted) — never a silent choice."""
    if start_raw is None and end_raw is None:
        start, end = calendar_feed.default_range(bd)
        return start, end, True
    missing = [pointer for pointer, value in (("/from", start_raw), ("/to", end_raw)) if value is None]
    if missing:
        raise errors.validation_failed([{
            "pointer": pointer, "code": "required",
            "message": "from and to are given together, or neither",
            "message_th": "ต้องระบุวันเริ่ม (from) และวันสิ้นสุด (to) คู่กัน หรือไม่ระบุทั้งคู่"} for pointer in missing])
    start, end = _date_param(start_raw, "/from"), _date_param(end_raw, "/to")
    if end < start:
        raise errors.validation_failed([{
            "pointer": "/to", "code": "range_reversed",
            "message": "to (%s) is before from (%s)" % (end, start),
            "message_th": "วันสิ้นสุดอยู่ก่อนวันเริ่ม"}])
    span = (end - start).days + 1
    if span > calendar_feed.MAX_SPAN_DAYS:
        raise errors.validation_failed([{
            "pointer": "/to", "code": "range_too_long", "max_days": calendar_feed.MAX_SPAN_DAYS,
            "message": "the range is %d days; the calendar serves at most %d" % (span, calendar_feed.MAX_SPAN_DAYS),
            "message_th": "ช่วงวันที่ยาว %d วัน เกินที่ปฏิทินแสดงได้ (%d วัน)" % (span, calendar_feed.MAX_SPAN_DAYS)}])
    return start, end, False


def _officer(raw):
    if not raw:
        return None
    known = [row["uid"] for row in officers.registry()]
    if raw not in known:
        raise errors.validation_failed([{
            "pointer": "/officer", "code": "value_unknown", "known": known,
            "message": "officer %r is not in the registry" % raw,
            "message_th": "ไม่รู้จักเจ้าหน้าที่ที่ระบุ"}])
    return raw


@router.get("/v1/calendar")
def calendar_view(start: str = Query(default=None, alias="from"), end: str = Query(default=None, alias="to"),
                  officer: str = Query(default=None)):
    bd = settings.business_date
    start_d, end_d, defaulted = _range(start or None, end or None, bd)
    officer = _officer(officer)
    cs = cases_domain.for_current()
    cases_domain.detect_broken_ptps(cs, bd)          # the same first step GET /v1/today takes
    js = journey.for_current()
    reminders = today_router.reminders(days=(end_d - bd).days, officer=officer)
    journey_ptps, mirrored = calendar_feed.journey_ptps(js, cs, start_d, end_d, bd)
    items = (calendar_feed.next_actions(cs, start_d, end_d, bd)
             + calendar_feed.case_ptps(cs, start_d, end_d, bd)
             + journey_ptps
             + calendar_feed.reminder_batches(reminders["reminders"], start_d, end_d, bd,
                                              reminders["meta"].get("batch_label"))
             + calendar_feed.case_reviews(cs, start_d, end_d, bd)
             + calendar_feed.journey_reviews(js, cs, start_d, end_d, bd)
             + calendar_feed.case_issues(cs, start_d, end_d, bd)
             + calendar_feed.restructures(js, cs, start_d, end_d, bd)
             + calendar_feed.settlements(js, cs, start_d, end_d, bd)
             + calendar_feed.npl_buybacks(js, cs, start_d, end_d, bd))
    if officer:
        items = [row for row in items if row["kind"] in calendar_feed.UNSCOPED_KINDS or row["officer_uid"] == officer]
    items = calendar_feed.ordered(items)
    return {
        "items": items,
        "days": calendar_feed.day_totals(items, start_d, end_d),
        "meta": {
            "from": start_d.isoformat(), "to": end_d.isoformat(), "defaulted": defaulted,
            "business_date": str(bd), "max_span_days": calendar_feed.MAX_SPAN_DAYS,
            "officer": officer, "total": len(items),
            "by_kind": calendar_feed.count_by(items, "kind"),
            "by_source": calendar_feed.count_by(items, "source"),
            "officers": [{"uid": row["uid"], "display_name_th": row["display_name_th"]}
                         for row in officers.registry() if row["role"] == "OFFICER"],
            "not_dated": calendar_feed.not_dated(cs, js),
            "journey_ptps_mirrored": mirrored,
            "next_action_excluded": list(calendar_feed.NEXT_ACTION_EXCLUDED),
            "review_sla_hours": settings.review_sla_hours,
        },
    }
```

In `backend/app/main.py`, after `from .routers.login import router as login_router  # noqa: E402` (:1587):

```python
# Feedback Round 1 / WP6 (F16): the calendar — one dated list, a moved next action, personal notices.
from .routers.calendar import router as calendar_router  # noqa: E402
```

and after `app.include_router(login_router)` (:1599): `app.include_router(calendar_router)`.

- [ ] **Step 6: Run the tests, then the suite**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar.py tests/test_audit_coverage.py tests/test_today_and_pipeline.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest tests/`. Expected: the previous count + 11 passed. **Paste the count.**

- [ ] **Step 7: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C2a.msg" <<'EOF'
feat(calendar): GET /v1/calendar — one dated list from the stores that already hold dates, each item naming its store

Vault note 10 §3 WP6, ruling F16. Next actions, open promises (both registers, a mirrored one once), reminder batches with the reminders endpoint's own label, review SLA deadlines (hour or day precision, said), ticket deadlines, restructure, settlement and executed buy-back dates (indicative). Every day's total is served; a range refuses bad dates, a reversed or 43+ day span, and an unknown officer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add backend/app/calendar_feed.py backend/app/routers/calendar.py backend/tests/test_calendar.py
git commit -F "$(git rev-parse --git-dir)/C2a.msg" -- backend/app/calendar_feed.py backend/app/routers/calendar.py backend/app/main.py backend/tests/test_calendar.py
```

### Task C2b: Personal notices: `records.notice`, audited create/edit/delete, served on the calendar

**Files:**
- Modify: `backend/app/schema.sql` (append one block at END OF FILE, after any block P2/P3 appended)
- Create: `backend/app/notices.py`
- Modify: `backend/app/calendar_feed.py` (append `notices`), `backend/app/routers/calendar.py` (imports; `calendar_view` signature, notice rows, meta; three routes)
- Test: `backend/tests/test_calendar_notices.py` (create)

**Interfaces:**
- Consumes: `db.configured()`, `db.connect()`; `journey.customer_by_uid`; `audit.describe`; `settings.business_date`; C2a's `calendar_feed._item`, `_who`, and `UNSCOPED_KINDS` (NOTICE is never officer-scoped).
- Produces:
  - Table `records.notice(uid text pk, owner, title, on_date date, at_time time, customer_uid, note_text, done bool, created_at, updated_at, deleted_at, deleted_by)`, with index `notice_owner_on_idx`.
  - `notices.NoticeRefused(code, pointer, message, message_th).error()`; `notices.reset()`; `notices.new_uid() -> "ntc-<12 hex>"`; `notices.clean(body, partial) -> fields`.
  - `notices.create(owner, fields, uid)`, `notices.list_for(owner, start, end)`, `notices.update(owner, uid, fields) -> dict|None`, `notices.delete(owner, uid) -> dict|None`.
  - Public notice shape: `{uid, owner, title, on, time, customer_uid, text, done, created_at, updated_at, durable, note_th?}`.
  - `calendar_feed.notices(rows, cs, bd)` yields items of kind `NOTICE`, source `records.notice`, `facts {notice_uid, title, text, done, durable}`.
  - Routes:
    - `POST /v1/calendar/notices` (201 `{notice}`)
    - `PUT /v1/calendar/notices/{uid}` (200 `{notice}`)
    - `DELETE /v1/calendar/notices/{uid}` (200 `{notice}`)
  - Route refusals:
    - 422 `owner_required` (no X-Volt-Officer).
    - 422 `validation_failed` with pointers `/title`, `/on`, `/time`, `/customer_uid`, `/text`, `/done` or `/<unknown>`. Codes: `required`, `too_long`, `date_invalid`, `time_invalid`, `customer_unknown`, `done_invalid`, `field_unknown`, `nothing_to_change`.
    - 404 `not_found` for a missing notice, a deleted one, or **another person's** (existence is never leaked).
  - Audit acts: `NOTICE_CREATED`, `NOTICE_UPDATED`, `NOTICE_DELETED`, subject `("notice", uid)`. Detail carries `on`, `customer_uid`, `durable`, and changed field names. **Never title or text.**
  - `GET /v1/calendar` gains `meta.notices = {owner, scope: "OWNER_ONLY", durable, total}`.
- **Who sees what:** an Officer sees their own notices. **A Manager (or Owner) sees their own notices only.** F16 rules out sharing, so no role reads, edits or deletes another person's notice. A Manager's view of the team's dated work is the case items with `officer` unset.

**Pins:** `test_landing_schema.py:11-24` checks a subset (`<=`) of `landing`/`app` tables: 0. `conftest.py` truncates `landing` and `app` only; this task's tests clean `records.notice` themselves and reset the memory store in their own autouse fixture, so conftest is not touched: 0. No screen: density 0.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_calendar_notices.py
"""WP6 — personal notices: one owner, audited, never shared (F16)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import audit_store, db, migrate, notices
from app.main import app

client = TestClient(app)
NANTAPOL = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}
THIP = {"X-Volt-Officer": "thip", "X-Volt-Role": "OFFICER"}
MANAGER = {"X-Volt-Officer": "settasak", "X-Volt-Role": "MANAGER"}
WEEK = {"from": "2026-10-26", "to": "2026-11-01"}


@pytest.fixture(autouse=True)
def _fresh_notices():
    notices.reset()
    yield
    notices.reset()


def _latest():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _create(headers=NANTAPOL, **fields):
    body = dict({"title": "โทรตามสลิปเดือนกันยายน", "on": "2026-10-26"}, **fields)
    return client.post("/v1/calendar/notices", json=body, headers=headers)


def test_a_notice_is_created_for_its_owner_and_audited_without_its_words():
    r = _create(time="09:30", text="ขอสลิปจากลูกค้า")
    assert r.status_code == 201, r.json()
    n = r.json()["notice"]
    assert (n["owner"], n["on"], n["time"], n["done"]) == ("nantapol", "2026-10-26", "09:30", False)
    assert n["durable"] is False and n["note_th"]
    entry = _latest()
    assert entry["act"] == "NOTICE_CREATED" and (entry["subject_type"], entry["subject_uid"]) == ("notice", n["uid"])
    assert "สลิป" not in str(entry["detail"]) and entry["detail"]["on"] == "2026-10-26"


def test_the_calendar_serves_a_notice_to_its_owner_only_a_manager_included():
    uid = _create().json()["notice"]["uid"]
    mine = client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).json()
    row = next(i for i in mine["items"] if i["kind"] == "NOTICE")
    assert row["facts"]["notice_uid"] == uid and row["source"] == "records.notice"
    assert mine["meta"]["notices"] == {"owner": "nantapol", "scope": "OWNER_ONLY", "durable": False, "total": 1}
    for other in (THIP, MANAGER):
        theirs = client.get("/v1/calendar", params=WEEK, headers=other).json()
        assert not any(i["kind"] == "NOTICE" for i in theirs["items"])
    filtered = client.get("/v1/calendar", params=dict(WEEK, officer="thip"), headers=NANTAPOL).json()
    assert any(i["kind"] == "NOTICE" for i in filtered["items"])       # a notice is not a case item


def test_only_the_owner_edits_or_deletes_and_anyone_else_meets_a_404():
    uid = _create().json()["notice"]["uid"]
    assert client.put("/v1/calendar/notices/%s" % uid, json={"done": True}, headers=THIP).status_code == 404
    assert client.delete("/v1/calendar/notices/%s" % uid, headers=MANAGER).status_code == 404
    r = client.put("/v1/calendar/notices/%s" % uid, json={"done": True, "title": "โทรแล้ว"}, headers=NANTAPOL)
    assert r.status_code == 200 and r.json()["notice"]["done"] is True and r.json()["notice"]["title"] == "โทรแล้ว"
    entry = _latest()
    assert entry["act"] == "NOTICE_UPDATED" and entry["detail"]["fields"] == ["done", "title"]
    assert "โทรแล้ว" not in str(entry["detail"])
    assert client.delete("/v1/calendar/notices/%s" % uid, headers=NANTAPOL).status_code == 200
    assert _latest()["act"] == "NOTICE_DELETED"
    assert client.put("/v1/calendar/notices/%s" % uid, json={"done": False}, headers=NANTAPOL).status_code == 404


def test_bad_fields_are_refused_by_pointer_and_an_unknown_field_is_not_dropped():
    def err(**body):
        r = client.post("/v1/calendar/notices", json=body, headers=NANTAPOL)
        assert r.status_code == 422, r.json()
        return r.json()["errors"][0]
    assert err(on="2026-10-26")["pointer"] == "/title"
    assert err(title="x", on="26/10/2026")["code"] == "date_invalid"
    assert err(title="x", on="2030-10-26")["code"] == "date_invalid"
    assert err(title="x", on="2026-10-26", time="25:00")["code"] == "time_invalid"
    assert err(title="x", on="2026-10-26", customer_uid="nobody")["code"] == "customer_unknown"
    assert err(title="x", on="2026-10-26", done="yes")["code"] == "done_invalid"
    assert err(title="x", on="2026-10-26", colour="red")["code"] == "field_unknown"
    assert err(title="x" * 121, on="2026-10-26")["code"] == "too_long"


def test_a_notice_with_no_owner_and_an_edit_that_changes_nothing_are_refused():
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26"}, headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 422 and r.json()["code"] == "owner_required" and r.json()["message_th"]
    uid = _create().json()["notice"]["uid"]
    r = client.put("/v1/calendar/notices/%s" % uid, json={}, headers=NANTAPOL)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "nothing_to_change"


def test_a_notice_may_name_a_customer_and_carries_their_name_on_the_calendar():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    assert _create(customer_uid=uid).status_code == 201
    row = next(i for i in client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).json()["items"]
               if i["kind"] == "NOTICE")
    assert row["customer_uid"] == uid and row["display_name"]


def test_the_postgres_store_round_trips_and_keeps_owners_apart(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()        # the store opens its own conn.begin() (attachments ruling, 2026-09-15)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    day = date(2026, 10, 26)
    try:
        fields = notices.clean({"title": "t", "on": "2026-10-26", "time": "08:05"}, partial=False)
        n = notices.create("nantapol", fields, notices.new_uid())
        assert n["durable"] is True and (n["on"], n["time"]) == ("2026-10-26", "08:05")
        assert [r["uid"] for r in notices.list_for("nantapol", day, day)] == [n["uid"]]
        assert notices.list_for("thip", day, day) == []
        assert notices.update("thip", n["uid"], {"done": True}) is None
        assert notices.update("nantapol", n["uid"], {"done": True, "time": None})["done"] is True
        assert notices.delete("nantapol", n["uid"])["uid"] == n["uid"]
        assert notices.list_for("nantapol", day, day) == []
    finally:
        pg_conn.execute(text("delete from records.notice"))
        pg_conn.commit()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar_notices.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'notices' from 'app'`.

- [ ] **Step 3: The table**

Append to the END of `backend/app/schema.sql`:

```sql
-- Feedback Round 1 / WP6 (design F16): personal notices on the calendar. One owner each,
-- no sharing, no recurrence, no e-mail. Soft-deleted so the NOTICE_DELETED audit row
-- still points at a row. "on" and "time" are SQL words, hence on_date and at_time.
CREATE TABLE IF NOT EXISTS records.notice (
    uid           text        PRIMARY KEY,
    owner         text        NOT NULL,
    title         text        NOT NULL,
    on_date       date        NOT NULL,
    at_time       time,
    customer_uid  text,
    note_text     text,
    done          boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz,
    deleted_by    text
);
CREATE INDEX IF NOT EXISTS notice_owner_on_idx ON records.notice (owner, on_date) WHERE deleted_at IS NULL;
```

- [ ] **Step 4: The store**

```python
# backend/app/notices.py
"""Personal notices on the calendar — vault note 10 §3 WP6 (F16).

records.notice when a database is configured; a process dict labelled not-durable when
it is not — the attachments store's own seam (attachments/store.py). A notice belongs
to ONE owner: the acting identity (X-Volt-Officer, which the login middleware rewrites
to the session's own identity when AUTH_MODE is on). Nobody else reads, edits or
deletes it, a Manager included: F16 rules out sharing. Title and text are the owner's
words and never go into an audit row or a log.
"""
import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text

from . import db, journey
from .config import settings

NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — โน้ตนี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
FIELDS = ("title", "on", "time", "customer_uid", "text", "done")
COLUMNS = {"title": "title", "on": "on_date", "time": "at_time", "customer_uid": "customer_uid",
           "text": "note_text", "done": "done"}
SELECT = "uid, owner, title, on_date, at_time, customer_uid, note_text, done, created_at, updated_at"
TITLE_MAX, TEXT_MAX = 120, 2000
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_MEMORY = {}


class NoticeRefused(Exception):
    def __init__(self, code, pointer, message, message_th):
        super().__init__(message)
        self.code = code
        self.pointer = pointer
        self.message = message
        self.message_th = message_th

    def error(self):
        return {"pointer": self.pointer, "code": self.code, "message": self.message, "message_th": self.message_th}


def reset():
    _MEMORY.clear()


def new_uid():
    return "ntc-" + uuid.uuid4().hex[:12]


def _on(raw):
    value = str(raw or "")
    try:
        if len(value) != 10:
            raise ValueError(value)
        day = date.fromisoformat(value)
    except ValueError:
        raise NoticeRefused("date_invalid", "/on", "on must be a date (yyyy-mm-dd)",
                            "วันที่ของโน้ตไม่ถูกต้อง ใช้รูปแบบ ปี-เดือน-วัน")
    if abs(day.year - settings.business_date.year) > 2:
        raise NoticeRefused("date_invalid", "/on", "on is not within two years of the business date",
                            "วันที่ของโน้ตต้องอยู่ภายในสองปีจากวันทำการ")
    return day.isoformat()


def clean(body, partial):
    """The fields a notice may carry, checked. An unknown field is refused, never dropped."""
    body = body or {}
    unknown = sorted(key for key in body if key not in FIELDS and key != "by")
    if unknown:
        raise NoticeRefused("field_unknown", "/" + unknown[0], "unknown field %r" % unknown[0],
                            "ไม่รู้จักช่องข้อมูล %s" % unknown[0])
    out = {}
    if not partial or "title" in body:
        title = str(body.get("title") or "").strip()
        if not title:
            raise NoticeRefused("required", "/title", "a notice needs a title", "ต้องใส่หัวข้อโน้ต")
        if len(title) > TITLE_MAX:
            raise NoticeRefused("too_long", "/title", "title is at most %d characters" % TITLE_MAX,
                                "หัวข้อยาวได้ไม่เกิน %d ตัวอักษร" % TITLE_MAX)
        out["title"] = title
    if not partial or "on" in body:
        out["on"] = _on(body.get("on"))
    if "time" in body:
        raw = body.get("time")
        if raw in (None, ""):
            out["time"] = None
        elif not TIME_RE.match(str(raw)):
            raise NoticeRefused("time_invalid", "/time", "time is HH:MM, 00:00 to 23:59",
                                "เวลาไม่ถูกต้อง ใช้รูปแบบ ชั่วโมง:นาที")
        else:
            out["time"] = str(raw)
    if "customer_uid" in body:
        raw = body.get("customer_uid")
        if raw in (None, ""):
            out["customer_uid"] = None
        elif journey.customer_by_uid(str(raw)) is None:
            raise NoticeRefused("customer_unknown", "/customer_uid", "no customer %s" % raw, "ไม่พบลูกค้าที่ระบุ")
        else:
            out["customer_uid"] = str(raw)
    if "text" in body:
        value = str(body.get("text") or "").strip()
        if len(value) > TEXT_MAX:
            raise NoticeRefused("too_long", "/text", "text is at most %d characters" % TEXT_MAX,
                                "รายละเอียดยาวได้ไม่เกิน %d ตัวอักษร" % TEXT_MAX)
        out["text"] = value or None
    if "done" in body:
        if not isinstance(body.get("done"), bool):
            raise NoticeRefused("done_invalid", "/done", "done is true or false", "สถานะเสร็จต้องเป็น true หรือ false")
        out["done"] = body["done"]
    return out


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _public(row, durable):
    at_time = row.get("at_time")
    rec = {"uid": row["uid"], "owner": row["owner"], "title": row["title"], "on": _iso(row["on_date"]),
           "time": at_time.strftime("%H:%M") if hasattr(at_time, "strftime") else at_time,
           "customer_uid": row.get("customer_uid"), "text": row.get("note_text"), "done": bool(row.get("done")),
           "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at")),
           "durable": durable}
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
    return rec


def _bind(columns):
    """Date and time as Python objects for the driver; strings stay in the memory store."""
    out = dict(columns)
    if out.get("on_date"):
        out["on_date"] = date.fromisoformat(out["on_date"])
    if out.get("at_time"):
        out["at_time"] = datetime.strptime(out["at_time"], "%H:%M").time()
    return out


def _run(sql, params):
    conn = db.connect()
    try:
        with conn.begin():
            return conn.execute(text(sql), params).mappings().all()
    finally:
        conn.close()


def create(owner, fields, uid):
    now = datetime.now(timezone.utc)
    row = {"uid": uid, "owner": owner, "title": fields["title"], "on_date": fields["on"],
           "at_time": fields.get("time"), "customer_uid": fields.get("customer_uid"),
           "note_text": fields.get("text"), "done": bool(fields.get("done", False)),
           "created_at": now, "updated_at": now, "deleted_at": None, "deleted_by": None}
    if not db.configured():
        _MEMORY[uid] = row
        return _public(row, durable=False)
    got = _run("insert into records.notice (uid, owner, title, on_date, at_time, customer_uid, note_text, done) "
               "values (:uid, :owner, :title, :on_date, :at_time, :customer_uid, :note_text, :done) "
               "returning " + SELECT, _bind(row))
    return _public(dict(got[0]), durable=True)


def list_for(owner, start, end):
    """The owner's notices dated start..end (inclusive). Another owner's are never read."""
    if not owner:
        return []
    if not db.configured():
        rows = [r for r in _MEMORY.values() if r["owner"] == owner and r["deleted_at"] is None
                and start.isoformat() <= r["on_date"] <= end.isoformat()]
        rows.sort(key=lambda r: (r["on_date"], r["at_time"] or "", r["uid"]))
        return [_public(r, durable=False) for r in rows]
    rows = _run("select " + SELECT + " from records.notice where owner = :owner and deleted_at is null "
                "and on_date between :start and :end order by on_date, at_time nulls first, uid",
                {"owner": owner, "start": start, "end": end})
    return [_public(dict(r), durable=True) for r in rows]


def _mine(owner, uid):
    row = _MEMORY.get(uid)
    return row if row is not None and row["owner"] == owner and row["deleted_at"] is None else None


def update(owner, uid, fields):
    columns = {COLUMNS[field]: value for field, value in fields.items()}
    if not db.configured():
        row = _mine(owner, uid)
        if row is None:
            return None
        row.update(columns)
        row["updated_at"] = datetime.now(timezone.utc)
        return _public(row, durable=False)
    sets = ", ".join("%s = :%s" % (column, column) for column in columns)   # names from COLUMNS only
    got = _run("update records.notice set " + sets + ", updated_at = now() "
               "where uid = :uid and owner = :owner and deleted_at is null returning " + SELECT,
               dict(_bind(columns), uid=uid, owner=owner))
    return _public(dict(got[0]), durable=True) if got else None


def delete(owner, uid):
    if not db.configured():
        row = _mine(owner, uid)
        if row is None:
            return None
        row["deleted_at"], row["deleted_by"] = datetime.now(timezone.utc), owner
        return _public(row, durable=False)
    got = _run("update records.notice set deleted_at = now(), deleted_by = :owner "
               "where uid = :uid and owner = :owner and deleted_at is null returning " + SELECT,
               {"uid": uid, "owner": owner})
    return _public(dict(got[0]), durable=True) if got else None
```

- [ ] **Step 5: The feed, the calendar's notice rows and the three routes**

1. Append to `backend/app/calendar_feed.py`:

```python
def notices(rows, cs, bd):
    """records.notice — the caller's own notices (notices.list_for), never anyone else's."""
    return [_item("ntc:%s" % n["uid"], "NOTICE", "records.notice", n["on"], _who(n.get("customer_uid"), cs), False,
                  time=n.get("time"),
                  facts={"notice_uid": n["uid"], "title": n["title"], "text": n.get("text"),
                         "done": n["done"], "durable": n["durable"]})
            for n in rows]
```

2. In `backend/app/routers/calendar.py`, replace the import block

```python
from fastapi import APIRouter, Query

from .. import calendar_feed, cases as cases_domain, errors, journey, officers
```

with

```python
from fastapi import APIRouter, Body, Header, Query

from .. import audit, calendar_feed, cases as cases_domain, db, errors, journey, notices, officers
```

3. Replace the `calendar_view` signature

```python
def calendar_view(start: str = Query(default=None, alias="from"), end: str = Query(default=None, alias="to"),
                  officer: str = Query(default=None)):
```

with

```python
def calendar_view(start: str = Query(default=None, alias="from"), end: str = Query(default=None, alias="to"),
                  officer: str = Query(default=None), x_volt_officer: str = Header(default=None)):
```

4. Replace

```python
             + calendar_feed.npl_buybacks(js, cs, start_d, end_d, bd))
    if officer:
```

with

```python
             + calendar_feed.npl_buybacks(js, cs, start_d, end_d, bd))
    # F16: a notice is its owner's alone — X-Volt-Officer, which the login middleware
    # rewrites to the session's own identity when AUTH_MODE is on. No header, no notices.
    owner = (x_volt_officer or "").strip() or None
    notice_rows = notices.list_for(owner, start_d, end_d)
    items += calendar_feed.notices(notice_rows, cs, bd)
    if officer:
```

5. Replace

```python
            "review_sla_hours": settings.review_sla_hours,
        },
```

with

```python
            "review_sla_hours": settings.review_sla_hours,
            "notices": {"owner": owner, "scope": "OWNER_ONLY", "durable": db.configured(),
                        "total": len(notice_rows)},
        },
```

6. Append the routes:

```python
# --- personal notices (F16) ---------------------------------------------------------

def _owner(header):
    owner = (header or "").strip()
    if not owner:
        raise errors.Problem(code="owner_required", status=422, title="A notice needs an owner",
                             detail="X-Volt-Officer names the person a notice belongs to; it was empty",
                             message_th="ไม่ทราบว่าโน้ตนี้เป็นของใคร — เลือกชื่อผู้ใช้งานก่อน",
                             error_id="DEBT-CAL-0422")
    return owner


def _clean(body, partial):
    try:
        fields = notices.clean(body, partial)
    except notices.NoticeRefused as exc:
        raise errors.validation_failed([exc.error()])
    if partial and not fields:
        raise errors.validation_failed([{"pointer": "", "code": "nothing_to_change",
                                         "message": "the body changes nothing", "message_th": "ไม่มีข้อมูลที่เปลี่ยน"}])
    return fields


@router.post("/v1/calendar/notices", status_code=201)
def create_notice(body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    fields = _clean(body, partial=False)
    uid = notices.new_uid()
    # Audited before the write that can raise; never the title or the text.
    audit.describe(act="NOTICE_CREATED", subject=("notice", uid),
                   detail={"on": fields["on"], "customer_uid": fields.get("customer_uid"), "durable": db.configured()})
    return {"notice": notices.create(owner, fields, uid)}


@router.put("/v1/calendar/notices/{uid}")
def update_notice(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    fields = _clean(body, partial=True)
    detail = {"fields": sorted(fields)}
    if "done" in fields:
        detail["done"] = fields["done"]
    audit.describe(act="NOTICE_UPDATED", subject=("notice", uid), detail=detail)
    notice = notices.update(owner, uid, fields)
    if notice is None:
        raise errors.not_found("notice")        # someone else's is "not found" too — never leaked
    return {"notice": notice}


@router.delete("/v1/calendar/notices/{uid}")
def delete_notice(uid: str, x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    audit.describe(act="NOTICE_DELETED", subject=("notice", uid))
    notice = notices.delete(owner, uid)
    if notice is None:
        raise errors.not_found("notice")
    return {"notice": notice}
```

- [ ] **Step 6: Run the tests, the pins, then the suite**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar_notices.py tests/test_calendar.py tests/test_landing_schema.py tests/test_audit_coverage.py tests/test_attachments_store.py -v`
Expected: PASS. The Postgres test runs rather than skipping, because `VOLT_TEST_PG_URL` is set.
Run: `.venv/bin/python -m pytest tests/`. Expected: the previous count + 7 passed. **Paste the count.**

- [ ] **Step 7: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C2b.msg" <<'EOF'
feat(calendar): personal notices — records.notice, one owner each, audited create/edit/delete without their words

Vault note 10 §3 WP6, ruling F16 (no sharing, recurrence or e-mail). A Manager sees only their own notices; another person's notice is a 404. A memory store labelled not-durable serves when no database is configured, the attachments store's seam.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add backend/app/notices.py backend/tests/test_calendar_notices.py
git commit -F "$(git rev-parse --git-dir)/C2b.msg" -- backend/app/schema.sql backend/app/notices.py backend/app/calendar_feed.py backend/app/routers/calendar.py backend/tests/test_calendar_notices.py
```

### Task C2c: Move a next action to another day, with a reason, through `set_next_action`

**Files:**
- Modify: `backend/app/routers/calendar.py` (imports; one route appended)
- Test: `backend/tests/test_calendar_move.py` (create)

**Interfaces:**
- Consumes: `cases.set_next_action(state, case, action, on, by, note=None)` (cases.py:924-938). It raises `next_action_required`, `next_action_date_invalid` and `review_required`, and appends the `NEXT_ACTION_SET` event. Also consumes `today_router._case_or_404`, `who`, `problem_from`, `dictionary_problem`, `dictionaries.DictionaryError`, `audit.describe`.
- Produces: `POST /v1/calendar/next-actions/{customer_uid}:move`, body `{"on": "yyyy-mm-dd", "reason": "…", "by"?}`, returning 200 `{"case", "moved": {"action", "from", "to"}}`.
  - **Refusals:** 404 `not_found`; 422 `validation_failed` with `/reason` `reason_required` or `/on` `required`; 409 `next_action_unchanged`; plus every refusal `set_next_action` makes, passed through `problem_from`. The action code never changes on this route, only its day.
  - **Audit:** act `NEXT_ACTION_MOVED`, subject `("customer", uid)`, detail `{action, from, to, reason}`, described before `set_next_action` can raise. The case's own trail still gets `NEXT_ACTION_SET` from `set_next_action`.
  - **No role gate.** The existing `POST /v1/cases/by-customer/{uid}/next-action` (today.py:1003) has none, and the design names no role for a move. It runs under the prototype's access model, where any signed-in staff member works any case (Round A ruling on Task 22).
- **Why a calendar route and not the existing one:** the existing route takes no reason and does not describe an act. Changing it would edit a Round B hotspot (`routers/today.py`) and its callers. This route adds only the reason and the act, then calls the same domain function.

**Pins:** the existing next-action route and `test_cases.py` are untouched: 0. No screen: density 0.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_calendar_move.py
"""WP6 (F16) — a next action moved on the calendar goes through set_next_action, with a reason."""
from fastapi.testclient import TestClient

from app import audit_store
from app import cases as cases_domain
from app.config import settings
from app.main import app

BD = settings.business_date
HEAD = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _call_case():
    cs = cases_domain.for_current()
    return next(k for k in cs.cases.values()
                if k["next_action"] == "CALL" and k["next_action_on"] == str(BD) and not k["review_uid"])


def _move(c, customer_uid, **body):
    return c.post("/v1/calendar/next-actions/%s:move" % customer_uid, json=body, headers=HEAD)


def test_a_next_action_moves_to_another_day_with_its_reason_and_keeps_its_action():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="ลูกค้าขอให้โทรวันอังคาร")
    assert r.status_code == 200, r.json()
    assert r.json()["moved"] == {"action": "CALL", "from": str(BD), "to": "2026-10-27"}
    assert (case["next_action"], case["next_action_on"]) == ("CALL", "2026-10-27")
    assert case["next_action_set_by"] == "nantapol" and case["next_action_note"] == "ลูกค้าขอให้โทรวันอังคาร"
    event = cases_domain.for_current().events[-1]
    assert event["kind"] == "NEXT_ACTION_SET" and event["on"] == "2026-10-27"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "NEXT_ACTION_MOVED" and entry["subject_uid"] == case["customer_uid"]
    assert {k: entry["detail"][k] for k in ("action", "from", "to", "reason")} == {
        "action": "CALL", "from": str(BD), "to": "2026-10-27", "reason": "ลูกค้าขอให้โทรวันอังคาร"}
    week = c.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}, headers=HEAD).json()
    assert any(i["kind"] == "NEXT_ACTION" and i["customer_uid"] == case["customer_uid"] and i["on"] == "2026-10-27"
               for i in week["items"])


def test_a_move_without_a_reason_or_a_day_is_refused_and_nothing_moves():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="   ")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/reason"
    r = _move(c, case["customer_uid"], reason="x")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/on"
    assert case["next_action_on"] == str(BD)


def test_the_refusals_set_next_action_makes_are_this_routes_refusals():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="61024-02-20", reason="typo")
    assert r.status_code == 422 and r.json()["code"] == "next_action_date_invalid"
    case["next_action"] = "AWAIT_REVIEW"          # waiting on a review nobody raised (T5-03)
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="รอผู้จัดการ")
    assert r.status_code == 422 and r.json()["code"] == "review_required" and r.json()["message_th"]
    case["next_action"] = None
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="x")
    assert r.status_code == 422 and r.json()["code"] == "next_action_required"
    assert case["next_action_on"] == str(BD)


def test_a_move_to_the_day_it_is_already_on_is_a_conflict_not_a_silent_success():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on=str(BD), reason="x")
    assert r.status_code == 409 and r.json()["code"] == "next_action_unchanged" and r.json()["message_th"]


def test_an_unknown_customer_is_a_404():
    assert _move(_client(), "no-such-customer", on="2026-10-27", reason="x").status_code == 404
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar_move.py -v`
Expected: 5 failed. Each expects a problem or 200 and gets a 404/405 with no `moved` key; for example `KeyError: 'moved'` or `assert 404 == 422`.

- [ ] **Step 3: Implement**

In `backend/app/routers/calendar.py`, replace

```python
from .. import audit, calendar_feed, cases as cases_domain, db, errors, journey, notices, officers
from ..config import settings
```

with

```python
from .. import audit, calendar_feed, cases as cases_domain, db, dictionaries, errors, journey, notices, officers
from ..cases import CaseError
from ..config import settings
```

(If C2c runs before C2b, the line it replaces reads `from .. import calendar_feed, cases as cases_domain, errors, journey, officers`. In that case add `audit, dictionaries` to it and keep the rest.)

Append:

```python
# --- moving a next action (F16) -------------------------------------------------------

@router.post("/v1/calendar/next-actions/{customer_uid}:move")
def move_next_action(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """A next action moved to another day, with a reason, through cases.set_next_action —
    the function, the checks and the NEXT_ACTION_SET event every next-action write uses,
    so each refusal it makes (a blank action, a bad date, AWAIT_REVIEW with no review) is
    this route's refusal too. Only the day changes; the action code stays what it was."""
    cs = cases_domain.for_current()
    case = today_router._case_or_404(cs, customer_uid)
    reason = str(body.get("reason") or "").strip()
    to_raw = body.get("on")
    problems = []
    if not reason:
        problems.append({"pointer": "/reason", "code": "reason_required",
                         "message": "moving a next action needs a reason", "message_th": "ต้องระบุเหตุผลที่ย้ายวัน"})
    if not to_raw:
        problems.append({"pointer": "/on", "code": "required",
                         "message": "on names the day to move to", "message_th": "ต้องระบุวันที่จะย้ายไป"})
    if problems:
        raise errors.validation_failed(problems)
    from_on = case.get("next_action_on")
    if str(to_raw)[:10] == from_on:
        raise errors.Problem(code="next_action_unchanged", status=409, title="The next action is already on that day",
                             detail="%s is already due on %s" % (case.get("next_action"), from_on),
                             message_th="งานถัดไปอยู่วันนี้อยู่แล้ว", error_id="DEBT-CAL-0409")
    # Described before set_next_action can raise: a refused move still names what was asked.
    audit.describe(act="NEXT_ACTION_MOVED", subject=("customer", customer_uid),
                   detail={"action": case.get("next_action"), "from": from_on, "to": str(to_raw)[:10],
                           "reason": reason})
    try:
        cases_domain.set_next_action(cs, case, case.get("next_action"), to_raw,
                                     by=today_router.who(body, x_volt_officer), note=reason)
    except CaseError as exc:
        raise today_router.problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise today_router.dictionary_problem(exc)
    return {"case": case, "moved": {"action": case["next_action"], "from": from_on, "to": case["next_action_on"]}}
```

- [ ] **Step 4: Run the tests, the pins, then the suite**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/backend && VOLT_TEST_PG_URL='…/<task-db>…' .venv/bin/python -m pytest tests/test_calendar_move.py tests/test_calendar.py tests/test_audit_coverage.py tests/test_cases.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest tests/`. Expected: the previous count + 5 passed. **Paste the count.**

- [ ] **Step 5: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C2c.msg" <<'EOF'
feat(calendar): a next action moves to another day with a reason, through set_next_action and its refusals

Vault note 10 §3 WP6, ruling F16. POST /v1/calendar/next-actions/{customer_uid}:move keeps the action, changes the day, audits NEXT_ACTION_MOVED with from/to/reason, and refuses a blank reason, a missing or invalid day, the same day, and AWAIT_REVIEW without a review.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add backend/tests/test_calendar_move.py
git commit -F "$(git rev-parse --git-dir)/C2c.msg" -- backend/app/routers/calendar.py backend/tests/test_calendar_move.py
```

### Task C3a: The calendar screen: month grid, week list, route, rail row, and `/reminders` retired into it

**Files:**
- Create: `frontend/src/calendarRange.js`, `frontend/src/calendarRange.test.js`
- Create: `frontend/src/screens/Calendar.jsx`, `frontend/src/screens/Calendar.test.jsx`, `frontend/src/App.calendar.test.jsx`
- Create: `frontend/src/calendar.css`. Modify: `frontend/src/app.css` (after `@import './uat.css';`, :24)
- Modify: `frontend/src/api.js` (append after the last binding)
- Modify: `frontend/src/App.jsx`: import; `/calendar` route; B1's `/reminders` route and import
- Modify: `frontend/src/components/Shell.jsx`: B1's `/reminders` row in `GROUPS[1].items` (:40-43 at caddc4b)
- Modify: `frontend/src/components/NavIcon.jsx` (a `calendar` glyph in `PATHS`, :13-35)
- Modify: `frontend/src/i18n-journey.js`: `nav.calendar` after `nav.audit` (EN :308 / TH :742); the `cal.*` block before the closing `}` of `JOURNEY_EN` (:483) and `JOURNEY_TH` (:912)
- Modify: `frontend/src/screens/Reminders.jsx` (B1's file): the `embedded` prop
- **Numbered edit:** `frontend/src/components/Shell.test.jsx`; `frontend/src/screens/Reminders.test.jsx` only if Step 7 measures a failure

**Interfaces:**
- Consumes:
  - `GET /v1/calendar` (C2a) and its `items`, `days`, `meta.from/to/business_date/total/officers/not_dated`.
  - B1's `Reminders` default export and its `<details data-testid="reminders">` with `data-reminder-day`.
  - `useDictionary('NEXT_ACTION')`, `dictLabel`, `codeLabel` (CaseContactDrawer.jsx:79,105,112); `formatDate` (NextAction.jsx); `format` (Money.jsx:36); `Segmented` (PrefControls.jsx:13); `Problem`, `fromError`; `useRole`, `useOfficer`.
- Produces:
  - `api.calendar(params)`.
  - `calendarRange`: `GRID_DAYS`, `addDays(iso, n)`, `mondayOf(iso)`, `monthRange(iso) -> {from, to, month}`, `weekRange(iso) -> {from, to, month}`, `addMonths(iso, n)` (returns the first of the month).
  - `Calendar` (default), `MONTH_CHIPS = 3`, `itemLabel(item, t, lang, nextActionValues)`.
  - Route `/calendar`; `/reminders` becomes `<Navigate to="/calendar" replace />`; the rail row `{ to: '/calendar', icon: 'calendar', label: 'nav.calendar', key: null }`.
  - Test ids:
    - page: `calendar`, `cal-total`, `cal-range`, `cal-officer`, `cal-scope`, `cal-not-dated`
    - month grid: `cal-month` (`td[data-day]`, `aria-current="date"`), `cal-day-total-<on>`, `cal-day-all-<on>`, `cal-item-<uid>`
    - week list: `cal-week` (`section[data-day]`), `cal-week-total-<on>`, `cal-row-<uid>`
    - B1's own ids stay inside the reminders section.
  - i18n (journey table) `nav.calendar` plus `cal.*`, listed in Step 5. A grep for `'cal.` and `'nav.calendar` across the four tables and `prefs.jsx` found 0 hits on 2026-09-15.
- **Honesty about a busy day:** the served 2026-10-23 holds 99 items. The month cell always prints the served `total`, draws the first `MONTH_CHIPS`, and shows "ทั้งหมด {total}" whenever `total > MONTH_CHIPS`. The week list draws every served item. The screen compares numbers but never subtracts or sums them.

**Pins, measured:**
- `frontend/src/components/Shell.test.jsx:25-31` (`TH_ORDER`, `ROUTES`) and `:67-72` (the EN list) pin the rail rows. B1's numbered edit adds its reminders row to all three. **C3a replaces those 3 string literals** ('<B1's TH label>' → 'ปฏิทิน', '/reminders' → '/calendar', '<B1's EN label>' → 'Calendar'). The `links[1]` count assertion (:55-56) does not move, because the row stays below Today.
- If B1 added no rail row, C3a inserts the calendar row after `'วันนี้'` / `'/'` / `'Today'` instead: the same 3 literals, the same price.
- `frontend/src/screens/Reminders.test.jsx`: measured in Step 7 by running it. It keeps passing when it renders `<Reminders />` directly, because the component and its ids survive and `embedded` defaults to false. Any line that fails is listed and priced into the same numbered edit.
- **Edit number N** is the lowest of 36..39 not yet spent: `grep -rn "AUTHORISED TEST EDIT 3[6-9]" frontend/src backend/tests`. If all four are spent, STOP: C3a is blocked.
- Density: no census covers `/calendar`. Both density files run unchanged: 0.

- [ ] **Step 1: Pre-flight: measure B1 and pick N**

Run:

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
ls frontend/src/screens/Reminders.jsx frontend/src/screens/Reminders.test.jsx
grep -n "export default\|page-title\|ops-head\|data-testid=\"reminders\"\|api\.\w*(" frontend/src/screens/Reminders.jsx
grep -n "render\|MemoryRouter\|initialEntries\|vi.mock\|getByRole('heading'" frontend/src/screens/Reminders.test.jsx
grep -n "reminders" frontend/src/App.jsx frontend/src/components/Shell.jsx frontend/src/components/Shell.test.jsx
grep -rn "AUTHORISED TEST EDIT 3[6-9]" frontend/src backend/tests
```

Expected:
- Both files exist, and `Reminders.jsx` has a default export that renders `data-testid="reminders"`.
- The `App.jsx` route plus import, the `Shell.jsx` row, and three `Shell.test.jsx` literals.

Write down each of the following. Later steps paste them verbatim:
- (a) the api bindings `Reminders.jsx` calls at mount;
- (b) whether it renders page chrome (an `h1.page-title` / `header.ops-head`) around the block;
- (c) B1's three Shell.test.jsx literals;
- (d) N.

If `Reminders.jsx` is missing, STOP: C3a waits on B1.

- [ ] **Step 2: The range helper, test first**

```js
// frontend/src/calendarRange.test.js
import { describe, expect, it } from 'vitest'
import { GRID_DAYS, addDays, addMonths, mondayOf, monthRange, weekRange } from './calendarRange.js'

describe('calendarRange — calendar layout only, never a served figure', () => {
  it('starts a month grid on the Monday on or before the first, six weeks long (the server default too)', () => {
    expect(monthRange('2026-10-23')).toEqual({ from: '2026-09-28', to: '2026-11-08', month: '2026-10' })
    expect(GRID_DAYS).toBe(42)
  })
  it('starts February 2026 (a Sunday first) on the Monday before', () => {
    expect(monthRange('2026-02-10')).toEqual({ from: '2026-01-26', to: '2026-03-08', month: '2026-02' })
  })
  it('a week runs Monday to Sunday', () => {
    expect(weekRange('2026-10-23')).toEqual({ from: '2026-10-19', to: '2026-10-25', month: '2026-10' })
    expect(mondayOf('2026-11-01')).toBe('2026-10-26')
  })
  it('steps months across a year end and days across a month end, in UTC', () => {
    expect(addMonths('2026-12-15', 1)).toBe('2027-01-01')
    expect(addMonths('2026-01-31', -1)).toBe('2025-12-01')
    expect(addDays('2026-10-30', 7)).toBe('2026-11-06')
  })
})
```

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/calendarRange.test.js`. Expected: FAIL, `Failed to resolve import "./calendarRange.js"`.

```js
// frontend/src/calendarRange.js
// The calendar's date ranges (Feedback Round 1 / WP6). Layout arithmetic on calendar
// days — which Monday a grid starts on, which month comes next — never a figure the
// server owns (api.js:1-4). Days are yyyy-mm-dd strings handled in UTC, the rule
// NextAction.jsx's formatDate follows, so no local zone moves a day.
export const GRID_DAYS = 42

function toDate(iso) { return new Date(`${iso}T00:00:00Z`) }
function toIso(d) { return d.toISOString().slice(0, 10) }

export function addDays(iso, n) {
  const d = toDate(iso)
  d.setUTCDate(d.getUTCDate() + n)
  return toIso(d)
}

export function mondayOf(iso) {
  return addDays(iso, -((toDate(iso).getUTCDay() + 6) % 7))
}

export function monthRange(iso) {
  const from = mondayOf(`${iso.slice(0, 7)}-01`)
  return { from, to: addDays(from, GRID_DAYS - 1), month: iso.slice(0, 7) }
}

export function weekRange(iso) {
  const from = mondayOf(iso)
  return { from, to: addDays(from, 6), month: iso.slice(0, 7) }
}

export function addMonths(iso, n) {
  const d = toDate(`${iso.slice(0, 7)}-01`)
  d.setUTCMonth(d.getUTCMonth() + n)
  return toIso(d)
}
```

Run it again. Expected: 4 passed.

- [ ] **Step 3: Write the failing screen tests**

In `vi.mock` below, add every binding recorded in Step 1(a) that `Reminders.jsx` calls at mount beyond `reminders`, each returning a Promise.

```jsx
// frontend/src/screens/Calendar.test.jsx
// WP6 (F16): one served list drawn as a month grid and a week list. A busy day names
// its size; the reminders block that left Today lives here now.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import Calendar from './Calendar.jsx'

vi.mock('../api.js', () => ({
  api: { calendar: vi.fn(), dictionary: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn() },
}))

const BD = '2026-10-23'
function addDays(iso, n) { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
function span(from, to) { return Math.round((new Date(`${to}T00:00:00Z`) - new Date(`${from}T00:00:00Z`)) / 86400000) + 1 }

const na = (i) => ({ uid: `na:cu-${i}`, kind: 'NEXT_ACTION', source: 'cases.next_action', on: BD, time: null,
  overdue: false, movable: true, customer_uid: `cu-${i}`, display_name: `ลูกค้าทดสอบ ${i}`, volt_id: `VL00${i}`,
  officer_uid: 'nantapol', facts: { action: 'CALL', set_by: 'SEED' } })
const ITEMS = [na(1), na(2), na(3), na(4), na(5),
  { uid: 'ptp:ptp-1', kind: 'PTP_DUE', source: 'cases.ptp', on: '2026-10-24', time: null, overdue: false, movable: false,
    customer_uid: 'cu-9', display_name: 'สมชาย ทำดี', volt_id: 'VL009', officer_uid: 'nantapol',
    facts: { ptp_uid: 'ptp-1', amount: '6985.42', origin: 'JOURNEY' } },
  { uid: 'rb:2026-11-07:D-3', kind: 'REMINDER_BATCH', source: 'today.reminders', on: '2026-11-07', time: null,
    overdue: false, movable: false, customer_uid: null, display_name: null, volt_id: null, officer_uid: null,
    facts: { label: 'D-3', count: 48, customers: [], batch_label: 'D-3 / D0' } },
  { uid: 'npl:npl-13:buyback', kind: 'NPL_BUYBACK', source: 'journey.npl_case', on: '2026-10-14', time: null,
    overdue: false, movable: false, customer_uid: 'cu-7', display_name: 'มานพ ทดสอบ', volt_id: null, officer_uid: 'noon',
    facts: { npl_uid: 'npl-13', amount: '254179.77', indicative: true, by: 'Owner' } },
]

function payload(from, n, items, meta = {}) {
  const to = addDays(from, n - 1)
  const inRange = items.filter((i) => i.on >= from && i.on <= to)
  const days = Array.from({ length: n }, (_, k) => {
    const on = addDays(from, k)
    return { on, total: inRange.filter((i) => i.on === on).length }
  })
  return { items: inRange, days, meta: { from, to, defaulted: false, business_date: BD, total: inRange.length,
    max_span_days: 42, officers: [{ uid: 'nantapol', display_name_th: 'nantapol' }, { uid: 'thip', display_name_th: 'ทิพย์อักษร' }],
    not_dated: { 'cases.issue': 0, 'journey.issue': 1 }, ...meta } }
}

const Page = () => (
  <MemoryRouter initialEntries={['/calendar']}>
    <Routes>
      <Route path="/calendar" element={<Calendar />} />
      <Route path="/customers/:uid" element={<p data-testid="case-page">case page</p>} />
    </Routes>
  </MemoryRouter>
)

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER'); setOfficer('nantapol')
  api.calendar.mockImplementation((p = {}) => Promise.resolve(p.from
    ? payload(p.from, span(p.from, p.to), ITEMS)
    : payload('2026-09-28', 42, ITEMS, { defaulted: true })))
  api.dictionary.mockImplementation((name) => Promise.resolve(name === 'NEXT_ACTION'
    ? { name, values: [{ code: 'CALL', label_th: 'โทรติดตาม', label_en: 'Call', active: true }] }
    : { name, values: [] }))
  api.reminders.mockResolvedValue({ reminders: [{ customer_uid: 'cu-2', display_name: 'ลูกค้าทดสอบ 2', volt_id: 'VL002',
    due_on: '2026-11-07', kind: 'D-3', overdue: false, officer_uid: 'nantapol' }],
  meta: { total: 1, offsets: [3, 0], batch_label: 'D-3 / D0', horizon: '2026-10-30' } })
})

describe('Calendar — one served list, month and week (WP6, F16)', () => {
  it("asks for the officer's own work first and draws the served six-week grid", async () => {
    renderIn('th', <Page />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalledWith({ officer: 'nantapol' }))
    const grid = await screen.findByTestId('cal-month')
    expect(grid.querySelectorAll('td[data-day]')).toHaveLength(42)
    expect(grid.querySelector(`td[data-day="${BD}"]`)).toHaveAttribute('aria-current', 'date')
    expect(screen.getByTestId('cal-total')).toHaveTextContent('8')
  })

  it('names how many a busy day holds and never cuts silently: three chips, then All n', async () => {
    renderIn('th', <Page />)
    const cell = (await screen.findByTestId('cal-month')).querySelector(`td[data-day="${BD}"]`)
    expect(within(cell).getByTestId(`cal-day-total-${BD}`)).toHaveTextContent('5 รายการ')
    expect(cell.querySelectorAll('.cal-day__list li')).toHaveLength(3)
    expect(within(cell).getByTestId(`cal-day-all-${BD}`)).toHaveTextContent('ทั้งหมด 5')
    expect(within(cell).getByTestId('cal-item-na:cu-1')).toHaveTextContent('โทรติดตาม')
  })

  it('All n opens that week, asks for exactly that week, and lists every item of the day', async () => {
    renderIn('th', <Page />)
    fireEvent.click(await screen.findByTestId(`cal-day-all-${BD}`))
    await waitFor(() => expect(api.calendar).toHaveBeenCalledWith({ from: '2026-10-19', to: '2026-10-25', officer: 'nantapol' }))
    const day = (await screen.findByTestId('cal-week')).querySelector(`section[data-day="${BD}"]`)
    expect(day.querySelectorAll('.cal-row')).toHaveLength(5)
    expect(within(day).getByTestId(`cal-week-total-${BD}`)).toHaveTextContent('5 รายการ')
  })

  it('a case item opens the case page', async () => {
    renderIn('th', <Page />)
    fireEvent.click(await screen.findByTestId('cal-item-na:cu-1'))
    expect(await screen.findByTestId('case-page')).toBeInTheDocument()
  })

  it('Everyone asks without an officer', async () => {
    renderIn('th', <Page />)
    const select = await screen.findByTestId('cal-officer')
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => expect(api.calendar).toHaveBeenLastCalledWith({}))
  })

  it("a Manager's calendar starts on everyone's work", async () => {
    setRole('MANAGER'); setOfficer('settasak')
    renderIn('th', <Page />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalledWith({}))
  })

  it('the indicative buy-back is badged in the week list, and every row names its store', async () => {
    renderIn('th', <Page />)
    fireEvent.click(await screen.findByRole('button', { name: /14\/10\/2026/ }))
    const row = await screen.findByTestId('cal-row-npl:npl-13:buyback')
    expect(row).toHaveTextContent('ตัวเลขชี้แนะ')
    expect(row).toHaveTextContent('เคส NPL')
  })

  it('a reminder batch opens the reminders block that moved here from Today', async () => {
    renderIn('th', <Page />)
    const fold = await screen.findByTestId('reminders')
    fireEvent.click(await screen.findByTestId('cal-item-rb:2026-11-07:D-3'))
    expect(fold.open).toBe(true)
  })

  it('a refusal is shown as the server said it', async () => {
    api.calendar.mockRejectedValue(Object.assign(new Error('x'), { problem: {
      code: 'validation_failed', message_th: 'ช่วงวันที่ยาวเกินที่ปฏิทินแสดงได้', errors: [] } }))
    renderIn('th', <Page />)
    expect(await screen.findByText('ช่วงวันที่ยาวเกินที่ปฏิทินแสดงได้')).toBeInTheDocument()
  })

  it('an item kind the screen does not know is printed as unknown, never mapped', async () => {
    api.calendar.mockImplementation(() => Promise.resolve(payload('2026-09-28', 42, [{ ...na(1), uid: 'x:1', kind: 'MYSTERY' }], { defaulted: true })))
    renderIn('en', <Page />)
    expect(await screen.findByTestId('cal-item-x:1')).toHaveTextContent('A MYSTERY item this screen does not know')
  })
})
```

```jsx
// frontend/src/App.calendar.test.jsx
// WP6 / F11 → F16: B1's /reminders is retired into the calendar; the rail names it.
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from './test-utils.jsx'

vi.mock('./api.js', () => {
  const empty = () => Promise.resolve({
    items: [], rows: [], reviews: [], documents: [], reminders: [], values: [], dictionaries: {},
    run: {}, meta: { total: 0, open: 0, counts_by_tier: {}, tiers: [] },
  })
  const api = new Proxy({}, {
    get(target, prop) {
      if (typeof prop !== 'string') return undefined
      if (!(prop in target)) target[prop] = vi.fn(empty)
      return target[prop]
    },
  })
  return { api, get: vi.fn(empty), post: vi.fn(empty), put: vi.fn(empty), del: vi.fn(empty), CHANGED_EVENT: 'volt:changed' }
})

import App from './App.jsx'

describe('App — /reminders lands on the calendar', () => {
  it('redirects /reminders to /calendar and the rail row names the calendar', async () => {
    renderIn('th', <MemoryRouter initialEntries={['/reminders']}><App /></MemoryRouter>)
    expect(await screen.findByTestId('calendar')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ปฏิทิน/ })).toHaveAttribute('href', '/calendar')
  })
})
```

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/screens/Calendar.test.jsx src/App.calendar.test.jsx`
Expected: FAIL, `Failed to resolve import "./Calendar.jsx"`; the App test fails on `calendar` not found.

- [ ] **Step 4: The binding and the screen**

`frontend/src/api.js`, after the last binding in the `api` object (at caddc4b that is `addCaseNote`, :394):

```js
  // Feedback Round 1 / WP6 (F16) — the calendar (routers/calendar.py).
  calendar: (params) => get('/v1/calendar', params),
```

```jsx
// frontend/src/screens/Calendar.jsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { usePrefs } from '../prefs.jsx'
import { useRole, useOfficer } from '../components/role.jsx'
import { Problem } from '../components/Problem.jsx'
import { Segmented } from '../components/PrefControls.jsx'
import { fromError } from '../problem.js'
import { formatDate } from '../components/NextAction.jsx'
import { format as formatMoney } from '../components/Money.jsx'
import { codeLabel, dictLabel, useDictionary } from '../components/CaseContactDrawer.jsx'
import { addDays, addMonths, monthRange, weekRange } from '../calendarRange.js'
import Reminders from './Reminders.jsx'

// The calendar — vault note 10 §3 WP6, ruling F16: read, move a next action with a
// reason, personal notices; no recurrence, sharing or e-mail. Every item, every day's
// total and the range total are the server's (GET /v1/calendar, api.js:1-4): this
// screen groups the served list by day, in the served order, and never re-counts,
// re-sorts or re-dates it. Its only arithmetic is calendar layout (calendarRange.js).
//
// A busy day is honest about its size: a month cell ALWAYS names the served total,
// draws the first MONTH_CHIPS items, and offers "All n" — the week list draws every one.
export const MONTH_CHIPS = 3
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const KINDS = ['NEXT_ACTION', 'PTP_DUE', 'REMINDER_BATCH', 'REVIEW_SLA', 'ISSUE_DEADLINE',
  'RESTRUCTURE', 'SETTLEMENT', 'NPL_BUYBACK', 'NOTICE']
const PHASES = { RESTRUCTURE: ['PROPOSED', 'FIRST_DUE'], SETTLEMENT: ['PLAN_OFFERED', 'ARRANGEMENT_OPENED'] }

// A translated label, or the raw value when this screen has no words for it — never
// the nearest known one.
function known(t, key, raw) {
  const text = t(key)
  return text === key ? String(raw) : text
}

export function itemLabel(item, t, lang, nextActions) {
  const f = item.facts || {}
  switch (item.kind) {
    case 'NEXT_ACTION': return dictLabel(nextActions, f.action, lang) || String(f.action)
    case 'PTP_DUE': return t('cal.item.PTP_DUE', { amount: formatMoney(f.amount) })
    case 'REMINDER_BATCH': return t('cal.item.REMINDER_BATCH', { label: f.label, n: f.count })
    case 'REVIEW_SLA': return t('cal.item.REVIEW_SLA', { reason: codeLabel(f.reason, lang) || '—' })
    case 'ISSUE_DEADLINE': return t('cal.item.ISSUE_DEADLINE', { team: f.responsible_team || '—' })
    case 'RESTRUCTURE':
    case 'SETTLEMENT':
      return PHASES[item.kind].includes(f.phase)
        ? t(`cal.item.${item.kind}.${f.phase}`)
        : t('cal.item.unknown', { kind: `${item.kind} ${f.phase}` })
    case 'NPL_BUYBACK': return t('cal.item.NPL_BUYBACK', { amount: formatMoney(f.amount) })
    case 'NOTICE': return f.title || '—'
    default: return t('cal.item.unknown', { kind: String(item.kind) })
  }
}

function ItemChip({ item, t, lang, nextActions, onOpenReminders }) {
  const label = itemLabel(item, t, lang, nextActions)
  const cls = `cal-chip${item.overdue ? ' cal-chip--overdue' : ''}`
  const late = item.overdue ? <> · {t('cal.overdue')}</> : null
  if (item.kind === 'REMINDER_BATCH') {
    return (
      <button type="button" className={cls} data-testid={`cal-item-${item.uid}`} onClick={() => onOpenReminders(item.on)}>
        {label}
      </button>
    )
  }
  if (item.customer_uid) {
    return (
      <Link className={cls} data-testid={`cal-item-${item.uid}`} to={`/customers/${item.customer_uid}`}>
        {label} · {item.display_name || item.volt_id || item.customer_uid}{late}
      </Link>
    )
  }
  return <span className={cls} data-testid={`cal-item-${item.uid}`}>{label}{late}</span>
}

function MonthGrid({ days, byDay, month, bd, t, lang, nextActions, onOpenDay, onOpenReminders }) {
  const weeks = []
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7))
  return (
    <div className="cal-month-wrap">
      <table className="cal-month" data-testid="cal-month" aria-label={t('cal.monthCaption', { month: month || '' })}>
        <thead><tr>{WEEKDAYS.map((w) => <th key={w} scope="col">{t(`cal.wd.${w}`)}</th>)}</tr></thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0].on}>
              {week.map((day) => {
                const list = byDay.get(day.on) || []
                const cls = ['cal-day', month && day.on.slice(0, 7) !== month ? 'cal-day--outside' : '',
                  day.on === bd ? 'cal-day--today' : ''].filter(Boolean).join(' ')
                return (
                  <td key={day.on} className={cls} data-day={day.on} aria-current={day.on === bd ? 'date' : undefined}>
                    <div className="cal-day__head">
                      <button type="button" className="cal-day__num" onClick={() => onOpenDay(day.on)}
                              aria-label={t('cal.openDay', { date: formatDate(day.on) })}>
                        {day.on.slice(8, 10)}
                      </button>
                      {day.total > 0 && (
                        <span className="cal-day__total" data-testid={`cal-day-total-${day.on}`}>{t('cal.dayTotal', { n: day.total })}</span>
                      )}
                    </div>
                    <ul className="cal-day__list">
                      {list.slice(0, MONTH_CHIPS).map((item) => (
                        <li key={item.uid}>
                          <ItemChip item={item} t={t} lang={lang} nextActions={nextActions} onOpenReminders={onOpenReminders} />
                        </li>
                      ))}
                    </ul>
                    {day.total > MONTH_CHIPS && (
                      <button type="button" className="btn btn--quiet btn--sm cal-day__all" data-testid={`cal-day-all-${day.on}`}
                              onClick={() => onOpenDay(day.on)}>{t('cal.allOfDay', { n: day.total })}</button>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function WeekList({ days, byDay, bd, t, lang, nextActions, onOpenReminders }) {
  return (
    <div className="cal-week" data-testid="cal-week">
      {days.map((day, index) => {
        const list = byDay.get(day.on) || []
        const headId = `cal-week-${day.on}`
        return (
          <section key={day.on} className={`cal-week__day${day.on === bd ? ' cal-week__day--today' : ''}`}
                   aria-labelledby={headId} data-day={day.on}>
            <h2 className="cal-week__head" id={headId}>
              {t(`cal.wd.${WEEKDAYS[index % 7]}`)} {formatDate(day.on)}{' '}
              <span className="td-quiet" data-testid={`cal-week-total-${day.on}`}>{t('cal.dayTotal', { n: day.total })}</span>
            </h2>
            {list.length === 0 ? <p className="td-quiet">{t('cal.dayEmpty')}</p> : (
              <ul className="cal-week__list">
                {list.map((item) => (
                  <li key={item.uid} className="cal-row" data-testid={`cal-row-${item.uid}`}>
                    <span className="cal-row__time">{item.time || t('cal.allDay')}</span>
                    <span className="cal-row__kind">{KINDS.includes(item.kind) ? t(`cal.kind.${item.kind}`) : String(item.kind)}</span>
                    <ItemChip item={item} t={t} lang={lang} nextActions={nextActions} onOpenReminders={onOpenReminders} />
                    {item.kind === 'NPL_BUYBACK' && item.facts?.indicative && (
                      <span className="chip chip--held">{t('cal.indicative')}</span>
                    )}
                    <span className="td-quiet cal-row__src">{known(t, `cal.src.${item.source}`, item.source)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )
}

export default function Calendar() {
  const { t, lang } = usePrefs()
  const { role } = useRole()
  const { officer: me } = useOfficer()
  const nextActions = useDictionary('NEXT_ACTION')
  const [view, setView] = useState('month')
  const [anchor, setAnchor] = useState(null)        // a yyyy-mm-dd inside the range on screen
  const [req, setReq] = useState(null)              // null: the server's own default grid
  const [scopeOfficer, setScopeOfficer] = useState(role === 'OFFICER' ? me : '')
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const remindersRef = useRef(null)
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  useEffect(() => {
    if (typeof api.calendar !== 'function') return undefined
    let alive = true
    const params = { ...(req || {}) }
    if (scopeOfficer) params.officer = scopeOfficer
    setProblem(null)
    api.calendar(params)
      .then((d) => {
        if (!alive) return
        setData(d)
        setAnchor((a) => a || d?.meta?.business_date || d?.meta?.from || null)
      })
      .catch((e) => { if (alive) setProblem(fromError(e)) })
    return () => { alive = false }
  }, [req, scopeOfficer, reloadKey])

  const bd = data?.meta?.business_date || null
  const days = data?.days || []
  const byDay = useMemo(() => {
    const map = new Map()
    for (const item of data?.items || []) {
      if (!map.has(item.on)) map.set(item.on, [])
      map.get(item.on).push(item)
    }
    return map
  }, [data])
  const month = anchor ? anchor.slice(0, 7) : null

  function go(nextView, nextAnchor) {
    if (!nextAnchor) return
    const range = nextView === 'week' ? weekRange(nextAnchor) : monthRange(nextAnchor)
    setView(nextView)
    setAnchor(nextAnchor)
    setReq({ from: range.from, to: range.to })
  }
  const step = (n) => go(view, view === 'week' ? addDays(anchor, 7 * n) : addMonths(anchor, n))

  function openReminders(on) {
    const root = remindersRef.current
    const fold = root ? root.querySelector('details[data-testid="reminders"]') : null
    if (fold) fold.open = true
    const target = (root && on && root.querySelector(`[data-reminder-day="${on}"]`)) || fold || root
    if (target && typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'start' })
  }

  const notDated = Object.entries(data?.meta?.not_dated || {}).filter(([, n]) => n > 0)

  return (
    <div className="ops-page cal-page" data-testid="calendar">
      <header className="ops-head">
        <div className="ops-head__text">
          <h1 className="page-title">{t('cal.title')}</h1>
          <p className="page-sub">
            {bd ? t('cal.sub', { date: formatDate(bd) }) : t('common.loading')}
            {data?.meta && <> · <span data-testid="cal-total">{t('cal.total', { n: data.meta.total })}</span></>}
          </p>
        </div>
      </header>

      <div className="cal-toolbar">
        <Segmented label={t('cal.view')} name="cal-view" value={view} onChange={(v) => go(v, anchor)}
                   options={[{ value: 'month', label: t('cal.view.month') }, { value: 'week', label: t('cal.view.week') }]} />
        <button type="button" className="btn btn--sm" disabled={!anchor} onClick={() => step(-1)}>
          {t(view === 'week' ? 'cal.prevWeek' : 'cal.prevMonth')}
        </button>
        <button type="button" className="btn btn--sm" disabled={!bd} onClick={() => go(view, bd)}>{t('cal.today')}</button>
        <button type="button" className="btn btn--sm" disabled={!anchor} onClick={() => step(1)}>
          {t(view === 'week' ? 'cal.nextWeek' : 'cal.nextMonth')}
        </button>
        <span className="cal-range" data-testid="cal-range">
          {data?.meta?.from ? t('cal.range', { from: formatDate(data.meta.from), to: formatDate(data.meta.to) }) : ''}
        </span>
        <label className="ops-field cal-officer">
          <span className="ops-field__label">{t('cal.officer')}</span>
          <select className="ops-select" data-testid="cal-officer" value={scopeOfficer}
                  onChange={(e) => setScopeOfficer(e.target.value)}>
            <option value="">{t('cal.officer.all')}</option>
            {(data?.meta?.officers || []).map((o) => <option key={o.uid} value={o.uid}>{o.display_name_th || o.uid}</option>)}
          </select>
        </label>
      </div>

      {problem && <Problem problem={problem} endpoint="GET /v1/calendar" />}
      {!data && !problem && <p className="ops-muted">{t('common.loading')}</p>}

      {data && view === 'month' && (
        <MonthGrid days={days} byDay={byDay} month={month} bd={bd} t={t} lang={lang} nextActions={nextActions.values}
                   onOpenDay={(on) => go('week', on)} onOpenReminders={openReminders} />
      )}
      {data && view === 'week' && (
        <WeekList days={days} byDay={byDay} bd={bd} t={t} lang={lang} nextActions={nextActions.values}
                  onOpenReminders={openReminders} />
      )}

      <p className="td-quiet cal-scope" data-testid="cal-scope">{t('cal.scopeNote')}</p>
      {notDated.length > 0 && (
        <p className="td-quiet" data-testid="cal-not-dated">
          {notDated.map(([source, n]) => t('cal.notDated', { n, source: known(t, `cal.src.${source}`, source) })).join(' · ')}
        </p>
      )}

      <section className="cal-reminders" ref={remindersRef} aria-labelledby="cal-reminders-title">
        <h2 className="ad-h2" id="cal-reminders-title">{t('cal.reminders')}</h2>
        <Reminders embedded />
      </section>
    </div>
  )
}
```

```css
/* frontend/src/calendar.css — Feedback Round 1 / WP6. Tokens only, spacing in literal px. */
.cal-toolbar { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px; margin: 12px 0; }
.cal-range { font: var(--label-13); color: var(--ink-700); }
.cal-officer { min-width: 180px; }
.cal-month-wrap { overflow-x: auto; }
.cal-month { width: 100%; border-collapse: collapse; table-layout: fixed; }
.cal-month th { font: var(--caption-12); color: var(--ink-500); text-align: left; padding: 4px 6px; }
.cal-day { vertical-align: top; border: 1px solid var(--line-default); padding: 4px; min-width: 96px; height: 112px; }
.cal-day--outside { background: var(--surface-50); }
.cal-day--today { box-shadow: inset 0 0 0 2px var(--line-strong); }
.cal-day__head { display: flex; justify-content: space-between; align-items: center; gap: 4px; }
.cal-day__num { font: var(--label-13); color: var(--ink-800); background: none; border: 0; padding: 2px 4px; cursor: pointer; }
.cal-day__total { font: var(--caption-12); color: var(--ink-600); }
.cal-day__list { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.cal-chip {
  display: block; width: 100%; text-align: left; font: var(--caption-12); color: var(--ink-800);
  background: var(--surface-100); border: 1px solid var(--line-default); border-radius: 4px; padding: 1px 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cal-chip--overdue { border-color: var(--status-overdue); }
.cal-day__all { margin-top: 2px; }
.cal-week { display: flex; flex-direction: column; gap: 12px; }
.cal-week__day { border: 1px solid var(--line-default); border-radius: 6px; padding: 8px 12px; }
.cal-week__day--today { border-color: var(--line-strong); }
.cal-week__head { font: var(--body-strong-14); color: var(--ink-900); margin: 0 0 6px; }
.cal-week__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.cal-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.cal-row__time { font: var(--caption-12); color: var(--ink-600); min-width: 56px; }
.cal-row__kind { font: var(--label-13); color: var(--ink-700); }
.cal-row .cal-chip { display: inline-block; width: auto; max-width: 100%; }
.cal-row__acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.cal-move, .cal-notice {
  display: flex; flex-direction: column; gap: 8px; margin: 12px 0; padding: 12px;
  border: 1px solid var(--line-default); border-radius: 6px; background: var(--surface-50);
}
.cal-move__acts { display: flex; flex-wrap: wrap; gap: 8px; }
.cal-scope { margin: 8px 0; }
.cal-reminders { margin-top: 16px; }
```

`frontend/src/app.css`, after `@import './uat.css';` (:24): `@import './calendar.css';`. The css-chain test (ruling 67) requires every stylesheet to be reachable.

- [ ] **Step 5: Strings, icon, rail, routes, and the embedded reminders**

1. **Grep first:** `grep -n "'cal\.\|'nav\.calendar" frontend/src/i18n-*.js frontend/src/prefs.jsx`. Expected: no output.
2. `frontend/src/i18n-journey.js`: after `'nav.audit': 'Action log',` (:308) add `'nav.calendar': 'Calendar',`, and after `'nav.audit': 'บันทึกการทำงาน',` (:742) add `'nav.calendar': 'ปฏิทิน',`.
   - Before the closing `}` of `JOURNEY_EN` (:483) add:

```js
  // --- Feedback Round 1 / WP6 (F16) — the calendar -------------------------------
  'cal.title': 'Calendar',
  'cal.sub': 'Business date {date} · every dated item the stores hold, in one list',
  'cal.total': '{n} items in this range',
  'cal.view': 'View', 'cal.view.month': 'Month', 'cal.view.week': 'Week',
  'cal.prevMonth': 'Previous month', 'cal.nextMonth': 'Next month',
  'cal.prevWeek': 'Previous week', 'cal.nextWeek': 'Next week', 'cal.today': 'Business date',
  'cal.range': '{from} – {to}',
  'cal.officer': 'Work of', 'cal.officer.all': 'Everyone',
  'cal.monthCaption': 'Month {month}',
  'cal.wd.mon': 'Mon', 'cal.wd.tue': 'Tue', 'cal.wd.wed': 'Wed', 'cal.wd.thu': 'Thu',
  'cal.wd.fri': 'Fri', 'cal.wd.sat': 'Sat', 'cal.wd.sun': 'Sun',
  'cal.openDay': 'Open the week of {date}',
  'cal.dayTotal': '{n} items', 'cal.allOfDay': 'All {n}', 'cal.dayEmpty': 'Nothing dated on this day',
  'cal.allDay': 'All day', 'cal.overdue': 'overdue', 'cal.indicative': 'indicative',
  'cal.kind.NEXT_ACTION': 'Next action', 'cal.kind.PTP_DUE': 'Promise due', 'cal.kind.REMINDER_BATCH': 'Reminder batch',
  'cal.kind.REVIEW_SLA': 'Review answer due', 'cal.kind.ISSUE_DEADLINE': 'Ticket deadline', 'cal.kind.RESTRUCTURE': 'Restructure',
  'cal.kind.SETTLEMENT': 'Settlement', 'cal.kind.NPL_BUYBACK': 'NPL buy-back', 'cal.kind.NOTICE': 'My notice',
  'cal.item.PTP_DUE': 'Promise {amount}',
  'cal.item.REMINDER_BATCH': '{label} reminders · {n} customers',
  'cal.item.REVIEW_SLA': 'Answer due · {reason}',
  'cal.item.ISSUE_DEADLINE': 'Ticket due · {team}',
  'cal.item.RESTRUCTURE.PROPOSED': 'Restructure proposed',
  'cal.item.RESTRUCTURE.FIRST_DUE': 'First due on the new schedule',
  'cal.item.SETTLEMENT.PLAN_OFFERED': 'Settlement plan offered',
  'cal.item.SETTLEMENT.ARRANGEMENT_OPENED': 'Repayment arrangement opened',
  'cal.item.NPL_BUYBACK': 'Buy-back deed {amount}',
  'cal.item.unknown': 'A {kind} item this screen does not know',
  'cal.src.cases.next_action': 'case register', 'cal.src.cases.ptp': 'case promises', 'cal.src.journey.ptp': 'journey promises',
  'cal.src.today.reminders': 'reminder batch', 'cal.src.cases.review': 'case reviews', 'cal.src.journey.review': 'manager-review queue',
  'cal.src.cases.issue': 'case tickets', 'cal.src.journey.issue': 'journey service issues',
  'cal.src.journey.restructure': 'restructures', 'cal.src.journey.cash_case': 'cash ladder',
  'cal.src.journey.arrangement': 'repayment arrangements', 'cal.src.journey.npl_case': 'NPL cases',
  'cal.src.records.notice': 'my notices',
  'cal.scopeNote': 'Case items follow “Work of”. Notices are personal: each person sees only their own, a Manager included.',
  'cal.notDated': '{source}: {n} open with no date, not placed on the calendar',
  'cal.reminders': 'Reminder batches',
```

   - Before the closing `}` of `JOURNEY_TH` (:912) add:

```js
  // --- Feedback Round 1 / WP6 (F16) — the calendar -------------------------------
  'cal.title': 'ปฏิทิน',
  'cal.sub': 'วันทำการ {date} · ทุกรายการที่มีวันที่ในระบบ รวมเป็นรายการเดียว',
  'cal.total': '{n} รายการในช่วงนี้',
  'cal.view': 'มุมมอง', 'cal.view.month': 'เดือน', 'cal.view.week': 'สัปดาห์',
  'cal.prevMonth': 'เดือนก่อน', 'cal.nextMonth': 'เดือนถัดไป',
  'cal.prevWeek': 'สัปดาห์ก่อน', 'cal.nextWeek': 'สัปดาห์ถัดไป', 'cal.today': 'วันทำการ',
  'cal.range': '{from} – {to}',
  'cal.officer': 'งานของ', 'cal.officer.all': 'ทุกคน',
  'cal.monthCaption': 'เดือน {month}',
  'cal.wd.mon': 'จ.', 'cal.wd.tue': 'อ.', 'cal.wd.wed': 'พ.', 'cal.wd.thu': 'พฤ.',
  'cal.wd.fri': 'ศ.', 'cal.wd.sat': 'ส.', 'cal.wd.sun': 'อา.',
  'cal.openDay': 'เปิดสัปดาห์ของ {date}',
  'cal.dayTotal': '{n} รายการ', 'cal.allOfDay': 'ทั้งหมด {n}', 'cal.dayEmpty': 'ไม่มีรายการในวันนี้',
  'cal.allDay': 'ทั้งวัน', 'cal.overdue': 'เลยกำหนด', 'cal.indicative': 'ตัวเลขชี้แนะ',
  'cal.kind.NEXT_ACTION': 'งานถัดไป', 'cal.kind.PTP_DUE': 'นัดชำระ', 'cal.kind.REMINDER_BATCH': 'ชุดแจ้งเตือน',
  'cal.kind.REVIEW_SLA': 'กำหนดตอบคำขอตรวจ', 'cal.kind.ISSUE_DEADLINE': 'กำหนดเสร็จของตั๋ว', 'cal.kind.RESTRUCTURE': 'ปรับโครงสร้างหนี้',
  'cal.kind.SETTLEMENT': 'แผนชำระหนี้', 'cal.kind.NPL_BUYBACK': 'ซื้อคืน NPL', 'cal.kind.NOTICE': 'โน้ตของฉัน',
  'cal.item.PTP_DUE': 'นัดชำระ {amount}',
  'cal.item.REMINDER_BATCH': 'แจ้งเตือน {label} · {n} ราย',
  'cal.item.REVIEW_SLA': 'ครบกำหนดตอบ · {reason}',
  'cal.item.ISSUE_DEADLINE': 'ตั๋วครบกำหนด · {team}',
  'cal.item.RESTRUCTURE.PROPOSED': 'เสนอปรับโครงสร้างหนี้',
  'cal.item.RESTRUCTURE.FIRST_DUE': 'งวดแรกของตารางใหม่',
  'cal.item.SETTLEMENT.PLAN_OFFERED': 'เสนอแผนผ่อนชำระยอดคงค้าง',
  'cal.item.SETTLEMENT.ARRANGEMENT_OPENED': 'เริ่มข้อตกลงผ่อนชำระ',
  'cal.item.NPL_BUYBACK': 'สัญญาซื้อคืน {amount}',
  'cal.item.unknown': 'รายการ {kind} ที่หน้านี้ไม่รู้จัก',
  'cal.src.cases.next_action': 'ทะเบียนเคส', 'cal.src.cases.ptp': 'นัดชำระในเคส', 'cal.src.journey.ptp': 'นัดชำระในเส้นทางสัญญา',
  'cal.src.today.reminders': 'ชุดแจ้งเตือน', 'cal.src.cases.review': 'คำขอตรวจในเคส', 'cal.src.journey.review': 'คิวผู้จัดการตรวจ',
  'cal.src.cases.issue': 'ตั๋วในเคส', 'cal.src.journey.issue': 'ปัญหาบริการในเส้นทางสัญญา',
  'cal.src.journey.restructure': 'การปรับโครงสร้างหนี้', 'cal.src.journey.cash_case': 'บันไดบัญชีเงินสด',
  'cal.src.journey.arrangement': 'ข้อตกลงผ่อนชำระ', 'cal.src.journey.npl_case': 'เคส NPL',
  'cal.src.records.notice': 'โน้ตของฉัน',
  'cal.scopeNote': 'รายการของเคสเป็นไปตาม “งานของ” ส่วนโน้ตเป็นของส่วนตัว แต่ละคนเห็นเฉพาะของตัวเอง รวมถึงผู้จัดการ',
  'cal.notDated': '{source}: เปิดอยู่ {n} รายการที่ไม่มีวันที่ จึงไม่ได้วางบนปฏิทิน',
  'cal.reminders': 'ชุดแจ้งเตือน',
```

3. `frontend/src/components/NavIcon.jsx`, after the `today:` entry in `PATHS`:

```jsx
  // the calendar: a month of days — many dates, where Today's glyph is about one
  calendar: <><rect x="2.5" y="3.5" width="15" height="14" rx="2" /><path d="M2.5 7.5h15" /><path d="M6 11h1M9.5 11h1M13 11h1M6 14h1M9.5 14h1" /></>,
```

4. `frontend/src/components/Shell.jsx`: in `GROUPS[1].items`, replace B1's row whose `to` is `'/reminders'` (Step 1(c)) with:

```jsx
      // Feedback Round 1 / WP6 (F16): B1's /reminders row becomes the calendar, which holds the reminders block now.
      { to: '/calendar', icon: 'calendar', label: 'nav.calendar', key: null },
```

5. `frontend/src/App.jsx`: remove B1's `import Reminders from './screens/Reminders.jsx'`. After `import AuditLog from './screens/AuditLog.jsx'` add `import Calendar from './screens/Calendar.jsx'`. After `<Route path="/audit" element={<AuditLog />} />` add `<Route path="/calendar" element={<Calendar />} />`. Replace B1's `/reminders` route line with:

```jsx
        {/* Feedback Round 1 / WP6: B1's reminders screen is retired into the calendar (F11 → F16). */}
        <Route path="/reminders" element={<Navigate to="/calendar" replace />} />
```

6. `frontend/src/screens/Reminders.jsx`: add `embedded = false` to the default export's props. If Step 1(b) found page chrome (a `header.ops-head` / `h1.page-title` around the block), wrap exactly that chrome in `{!embedded && (…)}`. The `<details data-testid="reminders">` block, its fetch, its send button and every test id stay unchanged. If there is no chrome, the prop is accepted and unused. Add a one-line comment: `// WP6: embedded inside the calendar (C3a), the calendar's own heading names this section.`

- [ ] **Step 6: Run the new tests**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/calendarRange.test.js src/screens/Calendar.test.jsx src/App.calendar.test.jsx src/i18n.test.js src/css-chain.test.js`
Expected: PASS (4 + 10 + 1, plus the unchanged i18n and css-chain tests).

- [ ] **Step 7: Measure the pins, then spend edit N**

Run: `npx vitest run src/components/Shell.test.jsx src/components/Shell.rail.test.jsx src/screens/Reminders.test.jsx src/App.test.jsx src/api.test.js`
Expected before the edit:
- `Shell.test.jsx` fails two tests ('lists the … rail rows …' and 'translates the rail into English') on the three literals from Step 1(c).
- `Shell.rail.test.jsx`, `App.test.jsx` and `api.test.js` pass.
- `Reminders.test.jsx` passes if it renders `<Reminders />` directly. Otherwise, write down each failing line.

**Paste this output.** Then apply edit N to `frontend/src/components/Shell.test.jsx`:
- In `TH_ORDER`, replace B1's Thai label with `'ปฏิทิน'`.
- In `ROUTES`, replace `'/reminders'` with `'/calendar'`.
- In the English list inside 'translates the rail into English', replace B1's English label with `'Calendar'`.
- Add this comment directly above `const TH_ORDER`, filling N and B1's literals from Step 1:

```js
// AUTHORISED TEST EDIT <N> (Feedback Round 1 plan, Arina's approval 2026-09-15): '<B1 TH label>' → 'ปฏิทิน', '/reminders' → '/calendar', '<B1 EN label>' → 'Calendar'. Round C (WP6, task C3a) retires B1's /reminders screen into the calendar, so the rail row B1 added under Today now names the calendar. Measured before spending: 3 string literals in 2 test functions; links[1]'s count assertion does not move.
```

For every `Reminders.test.jsx` line that failed, change its entry path from `'/reminders'` to `'/calendar'`. Also list the lines (file:line, old → new) in the same comment block and in the commit message. **Re-run the five files. Expected: all green.**

- [ ] **Step 8: Density unchanged, suite, build**

Run: `npx vitest run src/density.test.jsx src/today-density.test.jsx`. Expected: the same census lines as C1b Step 5. **Paste them.**
Run: `npx vitest run && npm run build`. Expected: the previous frontend count + 15 tests, + 3 files, build ok. **Paste the count.**

- [ ] **Step 9: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C3a.msg" <<'EOF'
feat(calendar): the calendar screen — a served six-week grid that names each day's total, a week list with every item, and /reminders retired into it

Vault note 10 §3 WP6, ruling F16. Route /calendar and the rail row ปฏิทิน replace B1's /reminders (now a redirect); the reminders block mounts inside the calendar with its test ids unchanged. AUTHORISED TEST EDIT <N>: Shell.test.jsx rail literals (3) — measured; <Reminders.test.jsx lines, or "Reminders.test.jsx: 0">.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/calendarRange.js frontend/src/calendarRange.test.js frontend/src/screens/Calendar.jsx frontend/src/screens/Calendar.test.jsx frontend/src/App.calendar.test.jsx frontend/src/calendar.css
git commit -F "$(git rev-parse --git-dir)/C3a.msg" -- frontend/src/calendarRange.js frontend/src/calendarRange.test.js frontend/src/screens/Calendar.jsx frontend/src/screens/Calendar.test.jsx frontend/src/App.calendar.test.jsx frontend/src/calendar.css frontend/src/app.css frontend/src/api.js frontend/src/App.jsx frontend/src/components/Shell.jsx frontend/src/components/NavIcon.jsx frontend/src/i18n-journey.js frontend/src/screens/Reminders.jsx frontend/src/components/Shell.test.jsx frontend/src/screens/Reminders.test.jsx
```

(Drop `frontend/src/screens/Reminders.test.jsx` from the pathspec if Step 7 left it unchanged.)

### Task C3b: Move a next action with a reason (button or drop), and open the Save-contact dialog

**Files:**
- Modify: `frontend/src/screens/Calendar.jsx` (C3a's file; every edit below is anchored on C3a's code)
- Modify: `frontend/src/api.js` (append after C3a's `calendar` binding)
- Modify: `frontend/src/i18n-journey.js` (append to the `cal.*` blocks)
- Test: `frontend/src/screens/Calendar.move.test.jsx` (create)

**Interfaces:**
- Consumes:
  - `POST /v1/calendar/next-actions/{customer_uid}:move` (C2c).
  - `GET /v1/cases/by-customer/{uid}`, via `api.caseDetail`: `case`, `work_item`, `ptps`, `issues`, `unreachable_run`.
  - `CaseContactDrawer` with `item`, `officer`, `businessDate`, `onClose`, `onLogged`, mounted with `key={item.customer.uid}`. The drawer item is composed exactly as `CustomerCase.jsx:397-399` does (`{...work_item, case: {...case, open_ptp, open_issue}, unreachable_run}`).
- Produces:
  - `api.moveNextAction(customerUid, {on, reason})`.
  - Test ids: `cal-move` (the request panel), `cal-move-reason`, `cal-move-to`, `cal-move-confirm`, `cal-move-open-<customer_uid>`, `cal-log-<customer_uid>`.
  - i18n: `cal.logContact`, `cal.move.open`, `cal.move.title`, `cal.move.reason`, `cal.move.to`, `cal.move.confirm`, `cal.move.note`, `cal.dialogUnavailable`. Cancel reuses the existing `common.cancel` (i18n-journey.js:726).
- **Moving, by design:**
  - The **button path is primary and keyboard-complete**: "ย้ายวัน…" opens the panel with the reason field first, then the day, then confirm.
  - Dropping a next-action chip on another month cell only **opens the same panel with that day filled in**. Nothing moves until confirm. This keeps the 2026-09-09 rule that removed drag-to-move from the board (`Today.jsx:1617-1619`): a dragging movement never commits an act, and SC 2.5.7's single-pointer path is the button.
  - A refusal (for example `review_required`) renders through `<Problem>` inside the panel, and the panel stays open.

**Pins:** 0 (new test file; Calendar.test.jsx from C3a still passes because every new control is additive). Density: no census for `/calendar`: 0.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/screens/Calendar.move.test.jsx
// WP6 (F16): a next action moves with a reason — the button first, a drop only fills
// the day in — and the Save-contact dialog opens on the customer.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import Calendar from './Calendar.jsx'

vi.mock('../api.js', () => ({
  api: {
    calendar: vi.fn(), dictionary: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(),
    moveNextAction: vi.fn(), caseDetail: vi.fn(), logContact: vi.fn(), logCaseContact: vi.fn(),
  },
}))

const BD = '2026-10-23'
const ITEM = { uid: 'na:cu-1', kind: 'NEXT_ACTION', source: 'cases.next_action', on: BD, time: null, overdue: false,
  movable: true, customer_uid: 'cu-1', display_name: 'ลูกค้าทดสอบ 1', volt_id: 'VL001', officer_uid: 'nantapol',
  facts: { action: 'CALL', set_by: 'SEED' } }

function addDays(iso, n) { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
function payload(from, n) {
  const to = addDays(from, n - 1)
  const items = [ITEM].filter((i) => i.on >= from && i.on <= to)
  return { items, days: Array.from({ length: n }, (_, k) => ({ on: addDays(from, k), total: addDays(from, k) === BD ? items.length : 0 })),
    meta: { from, to, business_date: BD, total: items.length, officers: [{ uid: 'nantapol', display_name_th: 'nantapol' }], not_dated: {} } }
}

const Page = () => (
  <MemoryRouter initialEntries={['/calendar']}>
    <Routes><Route path="/calendar" element={<Calendar />} /></Routes>
  </MemoryRouter>
)

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER'); setOfficer('nantapol')
  api.calendar.mockImplementation((p = {}) => Promise.resolve(p.from === '2026-10-19' ? payload('2026-10-19', 7) : payload('2026-09-28', 42)))
  api.dictionary.mockResolvedValue({ values: [{ code: 'CALL', label_th: 'โทรติดตาม', label_en: 'Call' }] })
  api.reminders.mockResolvedValue({ reminders: [], meta: {} })
  api.moveNextAction.mockResolvedValue({ case: {}, moved: { action: 'CALL', from: BD, to: '2026-10-27' } })
  api.caseDetail.mockResolvedValue({
    case: { payment_status: 'LATE', dc_status: 'NO_ACTION', next_action: 'CALL', next_action_on: BD, open_ptp_uid: null, open_issue_uid: null },
    work_item: { customer: { uid: 'cu-1', customer_no: 'C-1', display_name: 'ลูกค้าทดสอบ 1', phone_masked: '09x-xxx-0001' },
      entity: 'SPV', aggregate_overdue: '1000.00', contact_lock: { state: 'OPEN' } },
    ptps: [], issues: [], contact_log: [], events: [], unreachable_run: null,
  })
})

async function openWeek() {
  renderIn('th', <Page />)
  fireEvent.click(await screen.findByRole('button', { name: /23\/10\/2026/ }))
  return screen.findByTestId('cal-row-na:cu-1')
}

describe('Calendar — moving a next action (WP6, F16)', () => {
  it('the move button opens a request panel, reason first, and moves only with a reason and a day', async () => {
    const row = await openWeek()
    fireEvent.click(within(row).getByTestId('cal-move-open-cu-1'))
    const panel = await screen.findByTestId('cal-move')
    const reason = within(panel).getByTestId('cal-move-reason')
    await waitFor(() => expect(reason).toHaveFocus())
    expect(within(panel).getByTestId('cal-move-confirm')).toBeDisabled()
    fireEvent.change(reason, { target: { value: 'ลูกค้าขอให้โทรวันอังคาร' } })
    expect(within(panel).getByTestId('cal-move-confirm')).toBeDisabled()      // still no day
    fireEvent.change(within(panel).getByTestId('cal-move-to'), { target: { value: '2026-10-27' } })
    const calls = api.calendar.mock.calls.length
    fireEvent.click(within(panel).getByTestId('cal-move-confirm'))
    await waitFor(() => expect(api.moveNextAction).toHaveBeenCalledWith('cu-1', { on: '2026-10-27', reason: 'ลูกค้าขอให้โทรวันอังคาร' }))
    await waitFor(() => expect(api.calendar.mock.calls.length).toBeGreaterThan(calls))
    expect(screen.queryByTestId('cal-move')).not.toBeInTheDocument()
  })

  it('dropping a next action on another day only fills that day into the same panel — nothing moves by itself', async () => {
    renderIn('th', <Page />)
    const grid = await screen.findByTestId('cal-month')
    const chip = await within(grid).findByTestId('cal-item-na:cu-1')
    expect(chip).toHaveAttribute('draggable', 'true')
    fireEvent.dragStart(chip, { dataTransfer: { setData: vi.fn(), effectAllowed: '' } })
    fireEvent.drop(grid.querySelector('td[data-day="2026-10-27"]'), { dataTransfer: { getData: () => 'na:cu-1' } })
    const panel = await screen.findByTestId('cal-move')
    expect(within(panel).getByTestId('cal-move-to')).toHaveValue('2026-10-27')
    expect(api.moveNextAction).not.toHaveBeenCalled()
  })

  it('a refused move shows the refusal and keeps the panel open', async () => {
    api.moveNextAction.mockRejectedValue(Object.assign(new Error('x'), { problem: {
      code: 'review_required', message_th: 'ยังไม่ได้ส่งคำถามให้ผู้จัดการ' } }))
    const row = await openWeek()
    fireEvent.click(within(row).getByTestId('cal-move-open-cu-1'))
    const panel = await screen.findByTestId('cal-move')
    fireEvent.change(within(panel).getByTestId('cal-move-reason'), { target: { value: 'รอผู้จัดการ' } })
    fireEvent.change(within(panel).getByTestId('cal-move-to'), { target: { value: '2026-10-27' } })
    fireEvent.click(within(panel).getByTestId('cal-move-confirm'))
    expect(await within(panel).findByText('ยังไม่ได้ส่งคำถามให้ผู้จัดการ')).toBeInTheDocument()
    expect(screen.getByTestId('cal-move')).toBeInTheDocument()
  })

  it("log contact opens the Save-contact dialog on that customer's own case", async () => {
    const row = await openWeek()
    fireEvent.click(within(row).getByTestId('cal-log-cu-1'))
    await waitFor(() => expect(api.caseDetail).toHaveBeenCalledWith('cu-1'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/screens/Calendar.move.test.jsx`
Expected: 4 failed. `Unable to find an element by: [data-testid="cal-move-open-cu-1"]`, and the chip has no `draggable` attribute.

- [ ] **Step 3: Binding and strings**

`frontend/src/api.js`, after `calendar: (params) => get('/v1/calendar', params),`:

```js
  moveNextAction: (customerUid, body) => post(`/v1/calendar/next-actions/${customerUid}:move`, body),
```

`frontend/src/i18n-journey.js`: first grep `grep -n "'cal\.move\|'cal\.logContact\|'cal\.dialogUnavailable" frontend/src/i18n-*.js` (expected: no output). Then, after `'cal.reminders': 'Reminder batches',` in `JOURNEY_EN`:

```js
  'cal.logContact': 'Log contact',
  'cal.move.open': 'Move to another day…',
  'cal.move.title': 'Move “{what}” for {name} from {from}',
  'cal.move.reason': 'Why it moves (required)',
  'cal.move.to': 'Move to',
  'cal.move.confirm': 'Move it',
  'cal.move.note': 'Only the day changes; the action stays the same. The move is recorded with your reason.',
  'cal.dialogUnavailable': 'This case has no work item to log a contact on',
```

and after `'cal.reminders': 'ชุดแจ้งเตือน',` in `JOURNEY_TH`:

```js
  'cal.logContact': 'บันทึกการติดต่อ',
  'cal.move.open': 'ย้ายวัน…',
  'cal.move.title': 'ย้าย “{what}” ของ {name} จากวันที่ {from}',
  'cal.move.reason': 'เหตุผลที่ย้าย (ต้องระบุ)',
  'cal.move.to': 'ย้ายไปวันที่',
  'cal.move.confirm': 'ย้าย',
  'cal.move.note': 'เปลี่ยนเฉพาะวัน งานยังเป็นงานเดิม ระบบบันทึกการย้ายพร้อมเหตุผลของคุณ',
  'cal.dialogUnavailable': 'เคสนี้ยังไม่มีรายการงานให้บันทึกการติดต่อ',
```

- [ ] **Step 4: The screen**

In `frontend/src/screens/Calendar.jsx`:

1. Replace `import { codeLabel, dictLabel, useDictionary } from '../components/CaseContactDrawer.jsx'` with

```jsx
import { CaseContactDrawer, codeLabel, dictLabel, useDictionary } from '../components/CaseContactDrawer.jsx'
```

2. In `ItemChip`, replace the case-item `Link` opening line

```jsx
      <Link className={cls} data-testid={`cal-item-${item.uid}`} to={`/customers/${item.customer_uid}`}>
```

with

```jsx
      <Link className={cls} data-testid={`cal-item-${item.uid}`} to={`/customers/${item.customer_uid}`}
            draggable={item.movable ? 'true' : undefined}
            onDragStart={item.movable ? (e) => { if (e.dataTransfer) e.dataTransfer.setData('text/plain', item.uid) } : undefined}>
```

3. Replace the `MonthGrid` signature line

```jsx
function MonthGrid({ days, byDay, month, bd, t, lang, nextActions, onOpenDay, onOpenReminders }) {
```

with

```jsx
function MonthGrid({ days, byDay, month, bd, t, lang, nextActions, onOpenDay, onOpenReminders, onDropItem }) {
```

and replace

```jsx
                  <td key={day.on} className={cls} data-day={day.on} aria-current={day.on === bd ? 'date' : undefined}>
```

with

```jsx
                  <td key={day.on} className={cls} data-day={day.on} aria-current={day.on === bd ? 'date' : undefined}
                      onDragOver={onDropItem ? (e) => e.preventDefault() : undefined}
                      onDrop={onDropItem ? (e) => { e.preventDefault(); onDropItem(e.dataTransfer?.getData('text/plain'), day.on) } : undefined}>
```

4. Replace the `WeekList` signature line

```jsx
function WeekList({ days, byDay, bd, t, lang, nextActions, onOpenReminders }) {
```

with

```jsx
function WeekList({ days, byDay, bd, t, lang, nextActions, onOpenReminders, renderActions }) {
```

and replace

```jsx
                    <span className="td-quiet cal-row__src">{known(t, `cal.src.${item.source}`, item.source)}</span>
```

with

```jsx
                    <span className="td-quiet cal-row__src">{known(t, `cal.src.${item.source}`, item.source)}</span>
                    {renderActions && renderActions(item)}
```

5. In `Calendar()`, replace

```jsx
  const remindersRef = useRef(null)
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
```

with

```jsx
  const remindersRef = useRef(null)
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
  const [move, setMove] = useState(null)             // {item, to, reason} while the request panel is open
  const [moveBusy, setMoveBusy] = useState(false)
  const [moveProblem, setMoveProblem] = useState(null)
  const moveReasonRef = useRef(null)
  const [drawerFor, setDrawerFor] = useState(null)   // the work item the Save-contact dialog opens on
  const [dialogProblem, setDialogProblem] = useState(null)
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  const moveUid = move?.item?.uid
  useEffect(() => { if (moveUid && moveReasonRef.current) moveReasonRef.current.focus() }, [moveUid])

  // The request panel is the ONE way a next action moves: the button opens it empty, a
  // drop opens it with the day filled in. Nothing moves until confirm (2026-09-09 rule).
  function openMove(item, to) {
    if (!item?.movable) return
    setMoveProblem(null)
    setMove({ item, to: to && to !== item.on ? to : '', reason: '' })
  }

  function dropItem(uid, on) {
    const item = (data?.items || []).find((i) => i.uid === uid)
    if (item) openMove(item, on)
  }

  async function submitMove() {
    if (!move || moveBusy || !move.reason.trim() || !move.to || typeof api.moveNextAction !== 'function') return
    setMoveBusy(true)
    setMoveProblem(null)
    try {
      await api.moveNextAction(move.item.customer_uid, { on: move.to, reason: move.reason.trim() })
      if (!mountedRef.current) return
      setMove(null)
      reload()
    } catch (e) {
      if (mountedRef.current) setMoveProblem(fromError(e))
    } finally {
      if (mountedRef.current) setMoveBusy(false)
    }
  }

  // The dialog's item is composed exactly as CustomerCase.jsx:397-399 composes its own.
  async function openDialog(customerUid) {
    if (typeof api.caseDetail !== 'function') return
    setDialogProblem(null)
    try {
      const d = await api.caseDetail(customerUid)
      if (!mountedRef.current) return
      if (!d?.work_item?.customer?.uid) {
        setDialogProblem({ code: 'work_item_missing', message_th: t('cal.dialogUnavailable') })
        return
      }
      const kase = d.case || {}
      const openPtp = (d.ptps || []).find((p) => p.uid === kase.open_ptp_uid) || null
      const openIssue = (d.issues || []).find((i) => i.uid === kase.open_issue_uid) || null
      setDrawerFor({ ...d.work_item, case: { ...kase, open_ptp: openPtp, open_issue: openIssue },
                     unreachable_run: d.unreachable_run ?? kase.unreachable_run })
    } catch (e) {
      if (mountedRef.current) setDialogProblem(fromError(e))
    }
  }

  const rowActions = (item) => (item.kind === 'NEXT_ACTION' && item.customer_uid ? (
    <div className="cal-row__acts">
      <button type="button" className="btn btn--sm" data-testid={`cal-log-${item.customer_uid}`}
              onClick={() => openDialog(item.customer_uid)}>{t('cal.logContact')}</button>
      {item.movable && (
        <button type="button" className="btn btn--quiet btn--sm" data-testid={`cal-move-open-${item.customer_uid}`}
                onClick={() => openMove(item)}>{t('cal.move.open')}</button>
      )}
    </div>
  ) : null)
```

6. Replace

```jsx
      {problem && <Problem problem={problem} endpoint="GET /v1/calendar" />}
```

with

```jsx
      {problem && <Problem problem={problem} endpoint="GET /v1/calendar" />}
      {dialogProblem && <Problem problem={dialogProblem} endpoint="GET /v1/cases/by-customer/{customer_uid}" />}
      {move && (
        <section className="cal-move" data-testid="cal-move" aria-labelledby="cal-move-title">
          <h2 className="ad-h2" id="cal-move-title">
            {t('cal.move.title', { what: itemLabel(move.item, t, lang, nextActions.values),
                                   name: move.item.display_name || move.item.customer_uid, from: formatDate(move.item.on) })}
          </h2>
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.move.reason')}</span>
            <textarea ref={moveReasonRef} className="ops-textarea" data-testid="cal-move-reason" value={move.reason}
                      onChange={(e) => { const value = e.target.value; setMove((m) => ({ ...m, reason: value })) }} />
          </label>
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.move.to')}</span>
            <input type="date" className="ops-input" data-testid="cal-move-to" value={move.to}
                   onChange={(e) => { const value = e.target.value; setMove((m) => ({ ...m, to: value })) }} />
          </label>
          <div className="cal-move__acts">
            <button type="button" className="btn btn--primary btn--sm" data-testid="cal-move-confirm"
                    disabled={moveBusy || !move.reason.trim() || !move.to} onClick={submitMove}>{t('cal.move.confirm')}</button>
            <button type="button" className="btn btn--sm" onClick={() => { setMove(null); setMoveProblem(null) }}>{t('common.cancel')}</button>
          </div>
          <p className="td-quiet">{t('cal.move.note')}</p>
          {moveProblem && <Problem problem={moveProblem} endpoint="POST /v1/calendar/next-actions/{customer_uid}:move" />}
        </section>
      )}
```

7. Replace

```jsx
                   onOpenDay={(on) => go('week', on)} onOpenReminders={openReminders} />
```

with

```jsx
                   onOpenDay={(on) => go('week', on)} onOpenReminders={openReminders} onDropItem={dropItem} />
```

and replace

```jsx
                  onOpenReminders={openReminders} />
```

with

```jsx
                  onOpenReminders={openReminders} renderActions={rowActions} />
```

8. Replace the page's last lines

```jsx
        <Reminders embedded />
      </section>
    </div>
```

with

```jsx
        <Reminders embedded />
      </section>

      {drawerFor && (
        <CaseContactDrawer
          key={drawerFor.customer.uid}
          item={drawerFor}
          officer={me}
          businessDate={bd}
          onClose={() => { setDrawerFor(null); reload() }}
          onLogged={reload}
        />
      )}
    </div>
```

- [ ] **Step 5: Focused tests, density, suite, build**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/screens/Calendar.move.test.jsx src/screens/Calendar.test.jsx src/App.calendar.test.jsx src/i18n.test.js src/components/CaseContactDrawer.test.jsx`
Expected: PASS (4 new; C3a's 10 unchanged; the drawer's own tests unchanged).
Run: `npx vitest run src/density.test.jsx src/today-density.test.jsx`. Expected: census lines unchanged. **Paste them.**
Run: `npx vitest run && npm run build`. Expected: the previous count + 4 tests, + 1 file; build ok. **Paste.**

- [ ] **Step 6: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C3b.msg" <<'EOF'
feat(calendar): move a next action with a reason — the button first, a drop only fills the day in — and open the Save-contact dialog from the calendar

Vault note 10 §3 WP6, ruling F16. The request panel is the one way a next action moves (the 2026-09-09 rule: no dragging movement commits an act); a refusal renders inside the panel. The dialog's item is composed as the case page composes it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/screens/Calendar.move.test.jsx
git commit -F "$(git rev-parse --git-dir)/C3b.msg" -- frontend/src/screens/Calendar.jsx frontend/src/api.js frontend/src/i18n-journey.js frontend/src/screens/Calendar.move.test.jsx
```

### Task C3c: Personal notices on the calendar: add, edit, done, delete

**Files:**
- Modify: `frontend/src/screens/Calendar.jsx` (anchored on C3a + C3b code)
- Modify: `frontend/src/api.js` (append after `moveNextAction`)
- Modify: `frontend/src/i18n-journey.js` (append to the `cal.*` blocks)
- Test: `frontend/src/screens/Calendar.notices.test.jsx` (create)

**Interfaces:**
- Consumes:
  - `POST /v1/calendar/notices`, `PUT /v1/calendar/notices/{uid}`, `DELETE /v1/calendar/notices/{uid}` (C2b).
  - NOTICE items with `facts {notice_uid, title, text, done, durable}`.
  - `api.workbook({q, limit})` for the customer picker (the same server search `PeakRow` uses).
  - `SearchSelect` in server-side mode (`query`/`onQuery`), with `className="ops-field" labelClassName="ops-field__label" triggerClassName="ops-select"`.
  - The existing `put` / `del` helpers (api.js:104-105).
- Produces:
  - `api.createNotice(body)`, `api.updateNotice(uid, body)`, `api.deleteNotice(uid)`.
  - Test ids: `cal-notice-new`, `cal-notice-form`, `cal-notice-title-input`, `cal-notice-on`, `cal-notice-time`, `cal-notice-customer` (with `-input`), `cal-notice-text`, `cal-notice-save`, `cal-notice-done-<uid>`, `cal-notice-edit-<uid>`, `cal-notice-delete-<uid>`, `cal-notice-delete-confirm-<uid>`, `cal-notice-volatile-<uid>`.
  - i18n: `cal.notice.new`, `.newTitle`, `.editTitle`, `.title`, `.on`, `.time`, `.customer`, `.noCustomer`, `.searchCustomer`, `.text`, `.save`, `.privateNote`, `.done`, `.edit`, `.delete`, `.deleteConfirm`, `.notDurable`.
- A notice is edited from the week list. In the month grid a notice is a chip: it links to the case when it names a customer, and otherwise is plain text.
- Delete takes two clicks, the same confirm-step shape as `PeakLink`'s retire. No `window.confirm`.

**Pins:** 0 (new test file; C3a/C3b tests untouched). Density: no census for `/calendar`: 0.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/screens/Calendar.notices.test.jsx
// WP6 (F16): personal notices — added, edited, marked done and deleted from the
// calendar; each person's own, no recurrence, no sharing, no e-mail.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import Calendar from './Calendar.jsx'

vi.mock('../api.js', () => ({
  api: {
    calendar: vi.fn(), dictionary: vi.fn(), reminders: vi.fn(), sendReminder: vi.fn(), workbook: vi.fn(),
    createNotice: vi.fn(), updateNotice: vi.fn(), deleteNotice: vi.fn(),
  },
}))

const BD = '2026-10-23'
const NOTICE = (facts = {}) => ({ uid: 'ntc:ntc-1', kind: 'NOTICE', source: 'records.notice', on: BD, time: '09:30',
  overdue: false, movable: false, customer_uid: null, display_name: null, volt_id: null, officer_uid: null,
  facts: { notice_uid: 'ntc-1', title: 'โทรตามสลิป', text: 'ขอสลิป', done: false, durable: true, ...facts } })

function addDays(iso, n) { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
function payload(from, n, items) {
  const to = addDays(from, n - 1)
  return { items, days: Array.from({ length: n }, (_, k) => ({ on: addDays(from, k), total: items.filter((i) => i.on === addDays(from, k)).length })),
    meta: { from, to, business_date: BD, total: items.length, officers: [], not_dated: {},
            notices: { owner: 'nantapol', scope: 'OWNER_ONLY', durable: true, total: items.length } } }
}

const Page = () => (
  <MemoryRouter initialEntries={['/calendar']}>
    <Routes><Route path="/calendar" element={<Calendar />} /></Routes>
  </MemoryRouter>
)

function serve(items) {
  api.calendar.mockImplementation((p = {}) => Promise.resolve(p.from === '2026-10-19'
    ? payload('2026-10-19', 7, items) : payload('2026-09-28', 42, items)))
}

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER'); setOfficer('nantapol')
  serve([NOTICE()])
  api.dictionary.mockResolvedValue({ values: [] })
  api.reminders.mockResolvedValue({ reminders: [], meta: {} })
  api.workbook.mockResolvedValue({ rows: [] })
  api.createNotice.mockResolvedValue({ notice: { uid: 'ntc-2' } })
  api.updateNotice.mockResolvedValue({ notice: { uid: 'ntc-1' } })
  api.deleteNotice.mockResolvedValue({ notice: { uid: 'ntc-1' } })
})

async function openWeekRow() {
  renderIn('th', <Page />)
  fireEvent.click(await screen.findByRole('button', { name: /23\/10\/2026/ }))
  return screen.findByTestId('cal-row-ntc:ntc-1')
}

describe('Calendar — personal notices (WP6, F16)', () => {
  it('adds a notice with a title and a day, sending nothing it was not given', async () => {
    renderIn('th', <Page />)
    await screen.findByTestId('cal-month')
    fireEvent.click(screen.getByTestId('cal-notice-new'))
    const form = await screen.findByTestId('cal-notice-form')
    expect(within(form).getByTestId('cal-notice-on')).toHaveValue(BD)
    expect(within(form).getByTestId('cal-notice-save')).toBeDisabled()
    fireEvent.change(within(form).getByTestId('cal-notice-title-input'), { target: { value: 'เตรียมเอกสาร' } })
    const calls = api.calendar.mock.calls.length
    fireEvent.click(within(form).getByTestId('cal-notice-save'))
    await waitFor(() => expect(api.createNotice).toHaveBeenCalledWith(
      { title: 'เตรียมเอกสาร', on: BD, time: null, text: null, customer_uid: null }))
    await waitFor(() => expect(api.calendar.mock.calls.length).toBeGreaterThan(calls))
    expect(screen.queryByTestId('cal-notice-form')).not.toBeInTheDocument()
  })

  it('marks a notice done, and deletes only on the second click', async () => {
    const row = await openWeekRow()
    fireEvent.click(within(row).getByTestId('cal-notice-done-ntc-1'))
    await waitFor(() => expect(api.updateNotice).toHaveBeenCalledWith('ntc-1', { done: true }))
    const again = await screen.findByTestId('cal-row-ntc:ntc-1')
    fireEvent.click(within(again).getByTestId('cal-notice-delete-ntc-1'))
    expect(api.deleteNotice).not.toHaveBeenCalled()
    fireEvent.click(within(again).getByTestId('cal-notice-delete-confirm-ntc-1'))
    await waitFor(() => expect(api.deleteNotice).toHaveBeenCalledWith('ntc-1'))
  })

  it('edit opens the form with the served values and saves them back', async () => {
    const row = await openWeekRow()
    fireEvent.click(within(row).getByTestId('cal-notice-edit-ntc-1'))
    const form = await screen.findByTestId('cal-notice-form')
    expect(within(form).getByTestId('cal-notice-title-input')).toHaveValue('โทรตามสลิป')
    expect(within(form).getByTestId('cal-notice-time')).toHaveValue('09:30')
    fireEvent.change(within(form).getByTestId('cal-notice-title-input'), { target: { value: 'โทรตามสลิปอีกครั้ง' } })
    fireEvent.click(within(form).getByTestId('cal-notice-save'))
    await waitFor(() => expect(api.updateNotice).toHaveBeenCalledWith('ntc-1',
      { title: 'โทรตามสลิปอีกครั้ง', on: BD, time: '09:30', text: 'ขอสลิป', customer_uid: null }))
  })

  it("a refused save shows the server's field refusal inside the form", async () => {
    api.createNotice.mockRejectedValue(Object.assign(new Error('x'), { problem: { code: 'validation_failed',
      message_th: 'ข้อมูลไม่ถูกต้อง', errors: [{ pointer: '/on', code: 'date_invalid', message_th: 'วันที่ของโน้ตต้องอยู่ภายในสองปีจากวันทำการ' }] } }))
    renderIn('th', <Page />)
    await screen.findByTestId('cal-month')
    fireEvent.click(screen.getByTestId('cal-notice-new'))
    const form = await screen.findByTestId('cal-notice-form')
    fireEvent.change(within(form).getByTestId('cal-notice-title-input'), { target: { value: 'x' } })
    fireEvent.click(within(form).getByTestId('cal-notice-save'))
    expect(await within(form).findByText(/วันที่ของโน้ตต้องอยู่ภายในสองปีจากวันทำการ/)).toBeInTheDocument()
  })

  it('a notice kept only in memory says it will not survive a restart', async () => {
    serve([NOTICE({ durable: false })])
    const row = await openWeekRow()
    expect(within(row).getByTestId('cal-notice-volatile-ntc-1')).toHaveTextContent('หายเมื่อรีสตาร์ท')
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/screens/Calendar.notices.test.jsx`
Expected: 5 failed. `Unable to find an element by: [data-testid="cal-notice-new"]` (or `cal-notice-done-ntc-1`).

- [ ] **Step 3: Bindings and strings**

`frontend/src/api.js`, after `moveNextAction: …,`:

```js
  createNotice: (body) => post('/v1/calendar/notices', body),
  updateNotice: (uid, body) => put(`/v1/calendar/notices/${uid}`, body),
  deleteNotice: (uid) => del(`/v1/calendar/notices/${uid}`),
```

`frontend/src/i18n-journey.js`: first grep `grep -n "'cal\.notice" frontend/src/i18n-*.js` (expected: no output). Then add after `'cal.dialogUnavailable': 'This case has no work item to log a contact on',`:

```js
  'cal.notice.new': 'Add a notice', 'cal.notice.newTitle': 'New notice', 'cal.notice.editTitle': 'Edit notice',
  'cal.notice.title': 'Title', 'cal.notice.on': 'Date', 'cal.notice.time': 'Time (optional)',
  'cal.notice.customer': 'Customer (optional)', 'cal.notice.noCustomer': 'No customer',
  'cal.notice.searchCustomer': 'Search a customer by name or number', 'cal.notice.text': 'Note (optional)',
  'cal.notice.save': 'Save notice',
  'cal.notice.privateNote': 'Only you see this notice. Nothing is sent and it does not repeat.',
  'cal.notice.done': 'Done', 'cal.notice.edit': 'Edit', 'cal.notice.delete': 'Delete', 'cal.notice.deleteConfirm': 'Yes, delete it',
  'cal.notice.notDurable': 'Not saved to the database — lost on restart',
```

and after `'cal.dialogUnavailable': 'เคสนี้ยังไม่มีรายการงานให้บันทึกการติดต่อ',`:

```js
  'cal.notice.new': 'เพิ่มโน้ต', 'cal.notice.newTitle': 'โน้ตใหม่', 'cal.notice.editTitle': 'แก้ไขโน้ต',
  'cal.notice.title': 'หัวข้อ', 'cal.notice.on': 'วันที่', 'cal.notice.time': 'เวลา (ไม่บังคับ)',
  'cal.notice.customer': 'ลูกค้า (ไม่บังคับ)', 'cal.notice.noCustomer': 'ไม่ผูกกับลูกค้า',
  'cal.notice.searchCustomer': 'ค้นหาลูกค้าด้วยชื่อหรือเลขลูกค้า', 'cal.notice.text': 'รายละเอียด (ไม่บังคับ)',
  'cal.notice.save': 'บันทึกโน้ต',
  'cal.notice.privateNote': 'โน้ตนี้เห็นเฉพาะคุณ ระบบไม่ส่งแจ้งเตือนและไม่ทำซ้ำ',
  'cal.notice.done': 'เสร็จแล้ว', 'cal.notice.edit': 'แก้ไข', 'cal.notice.delete': 'ลบ', 'cal.notice.deleteConfirm': 'ยืนยันลบ',
  'cal.notice.notDurable': 'ไม่ได้บันทึกลงฐานข้อมูล — หายเมื่อรีสตาร์ท',
```

- [ ] **Step 4: The screen**

In `frontend/src/screens/Calendar.jsx`:

1. After `import { Segmented } from '../components/PrefControls.jsx'` add:

```jsx
import { SearchSelect } from '../components/SearchSelect.jsx'
```

2. Replace

```jsx
  const rowActions = (item) => (item.kind === 'NEXT_ACTION' && item.customer_uid ? (
```

with

```jsx
  const [notice, setNotice] = useState(null)      // the form: {uid, title, on, time, text, customer_uid, customer_label}
  const [noticeBusy, setNoticeBusy] = useState(false)
  const [noticeProblem, setNoticeProblem] = useState(null)
  const [noticeQ, setNoticeQ] = useState('')
  const [noticeHits, setNoticeHits] = useState([])
  const [confirmDelete, setConfirmDelete] = useState(null)    // a notice uid waiting for the second click
  const [rowProblem, setRowProblem] = useState(null)          // {uid, problem}
  const noticeOpen = Boolean(notice)

  useEffect(() => {
    if (!noticeOpen || !noticeQ.trim() || typeof api.workbook !== 'function') { setNoticeHits([]); return undefined }
    let alive = true
    api.workbook({ q: noticeQ.trim(), limit: 8 })
      .then((d) => { if (alive) setNoticeHits(d?.rows || []) })
      .catch(() => { if (alive) setNoticeHits([]) })
    return () => { alive = false }
  }, [noticeOpen, noticeQ])

  function openNotice(item) {
    setNoticeProblem(null); setNoticeQ(''); setNoticeHits([])
    if (item) {
      const f = item.facts || {}
      setNotice({ uid: f.notice_uid, title: f.title || '', on: item.on, time: item.time || '', text: f.text || '',
                  customer_uid: item.customer_uid || '', customer_label: item.display_name || item.customer_uid || '' })
    } else {
      setNotice({ uid: null, title: '', on: anchor || bd || '', time: '', text: '', customer_uid: '', customer_label: '' })
    }
  }

  async function saveNotice() {
    if (!notice || noticeBusy || !notice.title.trim() || !notice.on) return
    const body = { title: notice.title.trim(), on: notice.on, time: notice.time || null,
                   text: notice.text.trim() || null, customer_uid: notice.customer_uid || null }
    setNoticeBusy(true); setNoticeProblem(null)
    try {
      if (notice.uid) await api.updateNotice(notice.uid, body)
      else await api.createNotice(body)
      if (!mountedRef.current) return
      setNotice(null)
      reload()
    } catch (e) {
      if (mountedRef.current) setNoticeProblem(fromError(e))
    } finally {
      if (mountedRef.current) setNoticeBusy(false)
    }
  }

  async function noticeAct(item, act) {
    const uid = item.facts?.notice_uid
    setRowProblem(null)
    try {
      if (act === 'done') await api.updateNotice(uid, { done: !item.facts.done })
      if (act === 'delete') await api.deleteNotice(uid)
      if (!mountedRef.current) return
      setConfirmDelete(null)
      reload()
    } catch (e) {
      if (mountedRef.current) setRowProblem({ uid, problem: fromError(e) })
    }
  }

  const noticeActions = (item) => {
    const uid = item.facts?.notice_uid
    return (
      <div className="cal-row__acts">
        <label className="ad-check">
          <input type="checkbox" data-testid={`cal-notice-done-${uid}`} checked={Boolean(item.facts?.done)}
                 onChange={() => noticeAct(item, 'done')} />{' '}{t('cal.notice.done')}
        </label>
        <button type="button" className="btn btn--sm" data-testid={`cal-notice-edit-${uid}`} onClick={() => openNotice(item)}>
          {t('cal.notice.edit')}
        </button>
        {confirmDelete === uid ? (
          <>
            <button type="button" className="btn btn--primary btn--sm" data-testid={`cal-notice-delete-confirm-${uid}`}
                    onClick={() => noticeAct(item, 'delete')}>{t('cal.notice.deleteConfirm')}</button>
            <button type="button" className="btn btn--sm" onClick={() => setConfirmDelete(null)}>{t('common.cancel')}</button>
          </>
        ) : (
          <button type="button" className="btn btn--quiet btn--sm" data-testid={`cal-notice-delete-${uid}`}
                  onClick={() => setConfirmDelete(uid)}>{t('cal.notice.delete')}</button>
        )}
        {item.facts?.durable === false && (
          <span className="td-quiet" data-testid={`cal-notice-volatile-${uid}`}>{t('cal.notice.notDurable')}</span>
        )}
        {rowProblem?.uid === uid && <Problem problem={rowProblem.problem} />}
      </div>
    )
  }

  const rowActions = (item) => (item.kind === 'NOTICE' ? noticeActions(item) : item.kind === 'NEXT_ACTION' && item.customer_uid ? (
```

3. Replace the toolbar's end

```jsx
            {(data?.meta?.officers || []).map((o) => <option key={o.uid} value={o.uid}>{o.display_name_th || o.uid}</option>)}
          </select>
        </label>
      </div>
```

with

```jsx
            {(data?.meta?.officers || []).map((o) => <option key={o.uid} value={o.uid}>{o.display_name_th || o.uid}</option>)}
          </select>
        </label>
        <button type="button" className="btn btn--sm" data-testid="cal-notice-new" onClick={() => openNotice(null)}>
          {t('cal.notice.new')}
        </button>
      </div>
```

4. Replace

```jsx
      {data && view === 'month' && (
```

with

```jsx
      {notice && (
        <section className="cal-notice" data-testid="cal-notice-form" aria-labelledby="cal-notice-heading">
          <h2 className="ad-h2" id="cal-notice-heading">{t(notice.uid ? 'cal.notice.editTitle' : 'cal.notice.newTitle')}</h2>
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.notice.title')}</span>
            <input className="ops-input" data-testid="cal-notice-title-input" maxLength={120} value={notice.title}
                   onChange={(e) => { const value = e.target.value; setNotice((n) => ({ ...n, title: value })) }} />
          </label>
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.notice.on')}</span>
            <input type="date" className="ops-input" data-testid="cal-notice-on" value={notice.on}
                   onChange={(e) => { const value = e.target.value; setNotice((n) => ({ ...n, on: value })) }} />
          </label>
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.notice.time')}</span>
            <input type="time" className="ops-input" data-testid="cal-notice-time" value={notice.time}
                   onChange={(e) => { const value = e.target.value; setNotice((n) => ({ ...n, time: value })) }} />
          </label>
          <SearchSelect
            className="ops-field"
            labelClassName="ops-field__label"
            triggerClassName="ops-select"
            label={t('cal.notice.customer')}
            value={notice.customer_uid}
            options={[
              ...(notice.customer_uid && !noticeHits.some((h) => h.customer.uid === notice.customer_uid)
                ? [{ value: notice.customer_uid, label: notice.customer_label || notice.customer_uid }] : []),
              ...noticeHits.map((h) => ({ value: h.customer.uid, label: `${h.customer.display_name} · ${h.customer.customer_no}` })),
            ]}
            emptyLabel={t('cal.notice.noCustomer')}
            onChange={(uid) => {
              const hit = noticeHits.find((h) => h.customer.uid === uid)
              setNotice((n) => ({ ...n, customer_uid: uid || '', customer_label: hit ? hit.customer.display_name : (uid ? n.customer_label : '') }))
            }}
            testid="cal-notice-customer"
            searchTestid="cal-notice-customer-input"
            searchPlaceholder={t('cal.notice.searchCustomer')}
            query={noticeQ}
            onQuery={setNoticeQ}
          />
          <label className="ops-field">
            <span className="ops-field__label">{t('cal.notice.text')}</span>
            <textarea className="ops-textarea" data-testid="cal-notice-text" maxLength={2000} value={notice.text}
                      onChange={(e) => { const value = e.target.value; setNotice((n) => ({ ...n, text: value })) }} />
          </label>
          <div className="cal-move__acts">
            <button type="button" className="btn btn--primary btn--sm" data-testid="cal-notice-save"
                    disabled={noticeBusy || !notice.title.trim() || !notice.on} onClick={saveNotice}>{t('cal.notice.save')}</button>
            <button type="button" className="btn btn--sm" onClick={() => setNotice(null)}>{t('common.cancel')}</button>
          </div>
          <p className="td-quiet">{t('cal.notice.privateNote')}</p>
          {noticeProblem && <Problem problem={noticeProblem} endpoint="/v1/calendar/notices" />}
        </section>
      )}
      {data && view === 'month' && (
```

- [ ] **Step 5: Focused tests, density, suite, build**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1/frontend && npx vitest run src/screens/Calendar.notices.test.jsx src/screens/Calendar.move.test.jsx src/screens/Calendar.test.jsx src/App.calendar.test.jsx src/i18n.test.js`
Expected: PASS (5 + 4 + 10 + 1 + i18n).
Run: `npx vitest run src/density.test.jsx src/today-density.test.jsx`. Expected: census lines unchanged. **Paste them.**
Run: `npx vitest run && npm run build`. Expected: the previous count + 5 tests, + 1 file; build ok. **Paste.**

- [ ] **Step 6: Commit**

```bash
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
cat > "$(git rev-parse --git-dir)/C3c.msg" <<'EOF'
feat(calendar): personal notices on the calendar — add, edit, mark done, delete on a second click, and a memory-only notice says so

Vault note 10 §3 WP6, ruling F16 (no recurrence, sharing or e-mail). The customer picker is SearchSelect over the work-book search; a refusal renders inside the form or the row.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013aCPgMHjDHyrqhVEUKAi1W
EOF
git add frontend/src/screens/Calendar.notices.test.jsx
git commit -F "$(git rev-parse --git-dir)/C3c.msg" -- frontend/src/screens/Calendar.jsx frontend/src/api.js frontend/src/i18n-journey.js frontend/src/screens/Calendar.notices.test.jsx
```

---

### Task C4: Round C closes: the harness, the counts, note 10

**Files:** none in the product tree. Outside the repo: the vault note `~/Documents/Obsidian Vault/Debt modules (self build)/10 - Feedback Round 1 - Design.md`, appending a new §11 after whatever Round B's close appended.

- [ ] **Step 1: The harness**

Run: `cd /Users/parattakorn/volt-debt-worktrees/feedback-r1 && git log --oneline -12 && git status --short | wc -l && ./scripts/verify_all.sh`
Expected: C1a…C3c on top of Round B's commits; 0 uncommitted paths; `EVERYTHING PASSED`.
- Backend: B15's count + 35 (C1a 12, C2a 11, C2b 7, C2c 5).
- Frontend: B15's count + 29 tests and + 6 files (C1b 5, C3a 15, C3b 4, C3c 5).
- e2e: 31 of 31.

**Paste all three.**

- [ ] **Step 2: The live-stack spot check (the Round A habit)**

With the harness's own server up (`verify_all.sh` leaves none running, so start one the way it does, on port 8099), run as a Manager:

```bash
curl -s 'http://127.0.0.1:8099/v1/pipelines/peak-report/doors'
curl -s -H 'X-Volt-Role: MANAGER' -H 'Content-Type: application/json' -d '{"source":"api"}' 'http://127.0.0.1:8099/v1/pipelines/peak-report:run'
curl -s -H 'X-Volt-Officer: nantapol' 'http://127.0.0.1:8099/v1/calendar'
```

Expected:
- Door `api` has state `not_configured`.
- The `:run` call answers 422 `integration_not_configured`, naming the two variables. No token appears.
- The calendar serves `meta.defaulted: true`, the six-week grid, and the busiest day's `total` (99 on the seeded book).

Never print a token or a password.

- [ ] **Step 3: Record it in note 10**

Append this section to note 10:
- `## 11. Round C landed — <date> (branch feedback-r1, not merged)`
- the three counts
- the numbered edit C3a spent (N, its literals, and the Reminders.test.jsx lines or 0)
- the production gaps below
- a Thai summary of 5–8 bullets

Production gaps to record (not fixed in Round C):
- (a) `records.notice` needs the same runtime grants as `records.*`: another session's staged `migrate.py` grant strings must read `landing, app, records`.
- (b) Door 2 stays `untested` until someone verifies a PEAK report endpoint against PEAK's documentation. Then `VERIFIED_ENDPOINT`, the adapter in `peak_reports.list_invoices`, and the payload mapping in `peak_service.run_api` are written together, with their tests.
- (c) The move route has no case-ownership check, the same as the existing next-action route (the prototype's access model).
- (d) No store holds a future NPL buy-back date. The calendar shows executed deeds only.

- [ ] **Step 4: No commit** (nothing in the tree changed). Tell the controller the counts and the vault note's new section.

---

## Self-review (P5)

**Spec coverage: design note 10 §3, line by line.**

*WP5*
- "`backend/app/integrations/peak_reports.py`, a new module (PKD-001 pins the existing one)" → C1a Step 3. The pin is at `test_peak_documents.py:23-28`, and C1a Step 6 re-runs it.
- "`list_invoices(since, instance)` behind `PEAK_REPORT_API_*` env names" → C1a `REQUIRED_ENV`, `list_invoices`, `.env.example`.
- "until the endpoint is verified … answers `not_configured` / `untested`" → `state()` and the `NotConfigured` / `Untested` raises; `VERIFIED_ENDPOINT = None`; no network code, and a test proves it.
- "`pipelines/peak_service.run_api()`" (note 11) → C1a Step 4. It refuses before any run starts, and a test proves `runs.latest` stays None.
- "a `{"source": "api"}` door on `routers/peak_pipeline.py`" (note 11) → C1a Step 5: 422 not configured, 501 untested or adapter missing, 403 non-Manager.
- "the Data sources card lists door 2 with that state in words" → C1b, in both languages; an unknown state is printed as unknown; a refused read is a `<Problem>`; no button.
- "the same honesty as the UNSENT draft state" → C1b's comment and the no-button rule.
- "No webhook receiver is built" → no route is added (C1a); `state()["webhook"] == "not_built"`; C1b says so in words.

*WP6*
- "Route `/calendar`, rail item ปฏิทิน" → C3a Step 5.4–5.5, priced as edit N.
- "`GET /v1/calendar?from&to` serves one list of dated things the stores already hold" → C2a. There is one serializer per store, and each item names its `source`.
  - "next actions" → `next_actions` (SEND_REMINDER excluded, served as batches; NONE_CLOSED excluded).
  - "PTP promise dates" → `case_ptps` and `journey_ptps`, both registers, a mirrored promise once (design §7).
  - "reminder batches (D-3/D0 — the block leaving Today)" → `reminder_batches` over `GET /v1/today/reminders`' own rows and labels; C3a mounts B1's block inside the calendar.
  - "review SLA deadlines" → `case_reviews` (hour precision) and `journey_reviews` (day precision, said).
  - "service-issue deadlines" → `case_issues`; journey issues hold no deadline and are counted in `not_dated`.
  - "restructure and settlement dates" → `restructures` (PROPOSED, FIRST_DUE) and `settlements` (cash SETTLEMENT_PLAN_60, ACTIVE arrangements).
  - "NPL buy-back dates" → `npl_buybacks` (executed deeds, amount badged indicative).
- "Plus personal notices (`records.notice`: owner, title, on, time, customer_uid, text, done) with create/edit/delete" → C2b (table, store, three audited routes, served in the list) and C3c (UI).
- "Month grid and week list" → C3a.
- "click → the case page or the dialog" → C3a (chip → case page) and C3b (log contact → the Save-contact dialog).
- "a next action can be moved to another day (it calls the existing `set_next_action`, reason required)" → C2c (route over `cases.set_next_action`, reason and day required, its refusals passed through) and C3b (button panel; a drop fills the day in).
- "No recurrence, no sharing, no e-mail (F16)" → none built. Notices are owner-only for every role (a C2b test covers a Manager); the UI note says nothing is sent or repeated.
- Dispatch extras:
  - "a range filter that refuses bad dates (422) and caps the span" → C2a `_range` (42 days).
  - "notices are per owner … say what a Manager sees" → C2b Interfaces: a Manager sees only their own notices.
  - "no silent truncation" → C2a serves every item and every day's total; C3a's cell prints the total and "All n", the week list draws all, and a test covers it.
  - "`/reminders` from B1 retired into the calendar … one numbered edit" → C3a Steps 1, 5.5, 7.

**Placeholder scan.** No "TBD", no "add validation", no "similar to Task N". Four values are measured at run time rather than guessed, and each step says how to measure it:
- C3a's edit number N (the lowest unspent of 36–39, by grep);
- B1's three rail literals and `Reminders.jsx`'s mount-time bindings (C3a Step 1);
- whether `Reminders.test.jsx` moves (C3a Step 7, by running it);
- B15's counts.

These depend on work that does not exist yet (Round B) and are not gaps in this plan.

**Name consistency.**
- `peak_reports.state()` feeds `GET /doors`, which `api.peakReportDoors()` reads and `PeakApiDoor` renders (`door.state`, `missing_env`).
- `calendar_feed.*` item shape `{uid, kind, source, on, time, overdue, movable, facts, customer_uid, display_name, volt_id, officer_uid}` is consumed by `Calendar.jsx`'s `itemLabel`, `ItemChip` and `WeekList`, with the same fact keys (`action`, `amount`, `label`, `count`, `reason`, `responsible_team`, `phase`, `indicative`, `notice_uid`, `title`, `text`, `done`, `durable`).
- `days: [{on, total}]` maps to `cal-day-total-<on>` and `cal-week-total-<on>`.
- `POST …/next-actions/{uid}:move {on, reason}` is called by `api.moveNextAction(uid, {on, reason})`.
- `POST/PUT/DELETE /v1/calendar/notices` are called by `api.createNotice` / `updateNotice` / `deleteNotice`, with body keys `title, on, time, text, customer_uid, done` matching `notices.FIELDS`.
- `MAX_SPAN_DAYS = 42` matches `calendarRange.GRID_DAYS = 42`, and `default_range(bd)` matches `monthRange(bd)` (both tested on 2026-10-23: 2026-09-28 to 2026-11-08).

**Assumptions I could not verify in the code.**
1. **B1's shapes**, since the files are not on the branch: `Reminders.jsx`'s default export, its page chrome, its mount-time api calls, the rail literals B1 writes into `Shell.test.jsx`, and how `Reminders.test.jsx` renders. C3a measures all of them first. The scratch run used a stand-in: 2 Shell tests failed, as priced, and everything else passed.
2. **Round B leaves edits 36–39 partly unspent.** If all four are gone, C3a is blocked.
3. **`routers/today.py` `reminders(days, officer)`** keeps its signature and row keys through B2. C2a Step 1 checks.
4. **The design's words are read against stores that do not use them.**
   - "Settlement dates" = the cash ladder's SETTLEMENT_PLAN_60 stage date plus ACTIVE repayment arrangements' `opened_on`. No store has a field named settlement date.
   - "NPL buy-back dates" = executed deeds only. No store holds a future buy-back date.
   - "Review SLA" for the manager-review queue borrows `review_sla_hours` at day precision, because that register stores no time and has no SLA of its own.
5. **Drag.** The 2026-09-09 spec removed drag from the board (`Today.jsx:1617-1619`). The dispatch asks for "drag/move". C3b keeps the button path primary, and a drop only fills the panel's day. If Arina's reading is "no drag anywhere", drop the drag diff (C3b Step 4.2–4.3 and the second test): the button path stands alone.
6. **HTTP status for `untested` and `adapter_missing` is 501**, a new `DEBT-INT-0501`. The house has no precedent for "door exists, not open". 503 would read as an outage, and 422 as the caller's mistake.
7. **`records.notice` and runtime grants:** the grants in another session's staged `migrate.py` must include `records`. This is carried as production gap (a).
8. **The PEAK API itself:** nothing about its endpoint, auth or payload was assumed, by design (F19).
9. **Concurrency on the branch:** at 15:30 another session had an uncommitted `PeakReportCard.jsx` edit in this worktree. C1b's Step 0 stops if the file is dirty. The Round A Postgres test database `volt_feedback_r1` was used for this plan's scratch runs; they created `records.notice` there. It is harmless (`CREATE … IF NOT EXISTS`), but it is a side effect on a shared test database.
