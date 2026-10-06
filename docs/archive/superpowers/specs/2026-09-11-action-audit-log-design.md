# Design — the action audit log

**Written 2026-09-11** through `superpowers:brainstorming`, against the tree on branch
`design-team` at `3e17e02`. Every decision below was ruled on by Arina in that session and is
attributed inline. **Nothing here has been built.**

---

## 0. Standing

This is a design for a **new subsystem of the prototype**. On the Requirements Amendment v2.6 §1
ladder it carries no rank of its own; it implements an instruction given directly by Arina on
2026-09-11:

> "adding the new seperate feature that can track all the action from user show the structural
> action log for user can audit all theaction. make it immutable."

Where it touches existing behaviour it says so, and it changes no domain rule.

---

## 1. What is true of the tree today

Four facts, all read rather than assumed.

**1.1 — There are 91 acts.** Counted across `backend/app/main.py` and `backend/app/routers/*.py`:
9 `@app.post`, 1 `@app.put`, 3 `@app.delete`, 72 `@router.post`, 5 `@router.put`, 1
`@router.delete`. That is the surface any "track all the action" claim has to cover, and it grows.

**1.2 — Three partial trails already exist, and none of them is an audit log.**

| trail | where | what it holds | lifetime |
|---|---|---|---|
| `CaseState.events` | `cases.py:76`, commented "audit trail" | 21 event kinds — `CASE_OPENED`, `DC_STATUS_SET`, `PTP_BROKEN`, `POWER_*`, `BOARD_AUTO_MOVED` … | per session, in memory |
| `ExportLog.entries` | `workbook_exports.py` | who took the work book out, and why (rulings 72/74) | per session, in memory |
| `JourneyState.overrides` | `journey.py:92` | R14 local overrides with provenance | per session, in memory |

Each is real and each is partial. None covers the 91 acts, none is ordered against the others,
and all three are per-session state that a deploy discards.

**1.3 — The actor is self-asserted, and the code already says so.** `tester_session`
(`main.py:177`) is explicit: *"The cookie identifies a BROWSER, not a person — it is isolation for
testing, not authentication. Who someone is comes from SSO, which this build does not have."* The
acting name reaches the backend as the `X-Volt-Officer` header or the body's `by`
(`routers/today.py:26`, `who()`), both **chosen by the client**.

**1.4 — Persistence is a seam, and session state is deliberately disposable.** `db.py` defines
three states — unset, reachable, configured-but-unreachable — and refuses in the third rather than
falling back. `session_store_db.py` stores session state as a **pickle keyed by code version**, and
says outright that *"a restart keeps a tester's work, a deploy does not, and that is the honest
trade."*

---

## 2. The problem, stated precisely

The prototype can say a great deal about *what the book looks like now* and very little about
*how it got that way, and who did it.* A question as ordinary as "who moved this customer to NPL
last Tuesday, and what reason did they give" cannot be answered from any one place, and after a
deploy it cannot be answered at all.

Three things follow, and the design is shaped by them:

- **Completeness must be structural, not remembered.** A trail that depends on each new act
  remembering to append is a trail with unknown gaps, and a trail with unknown gaps is worse than
  no trail: it invites confident conclusions from partial evidence (contract §1a).
- **The log must not overclaim.** Recording `actor: "nantapol"` as fact, from a string the client
  chose, would make every row a confident wrong value.
- **"Immutable" must mean something we can actually keep.** We own the database. Nothing stops a
  credential-holder editing a row. Promising immutability we cannot enforce is the same defect in a
  different coat.

---

## 3. Decisions (Arina, 2026-09-11)

| # | Question | Decision |
|---|---|---|
| D1 | Where does capture happen? | **Middleware, enriched by the domain.** One middleware records every non-GET request; domain code attaches business meaning where it matters. |
| D2 | What does "immutable" mean? | **Hash-chained, verifiable, honest about its store.** Own append-only table; runs in memory when `DATABASE_URL` is unset and says so on screen. |
| D3 | Does it log reads? | **Changes, plus opening a customer.** The 91 acts, plus `GET /v1/cases/by-customer/{uid}` — the read a data-subject complaint asks about. List and report views are not logged. |
| D4 | Who may read it? | **Everyone sees everything.** No role gate, no per-officer filtering. |
| D5 | How is it reached? | **A rail row in the ระบบ group**, decided by Claude on Arina's delegation ("decided the best decision by yours"). Rationale and price in §8. |

---

## 4. The entry

One row per act. Structured fields, never a formatted sentence — the screen formats, the log
records.

```
seq             int        monotonic, assigned at insert; no gaps in the NUMBERING
                           (an act that failed to record leaves no row and no seq —
                            see §5 "when the write itself fails")
at              timestamp  server UTC, never client-supplied
business_date   date       settings.business_date at the moment of the act
actor_claimed   text       the name the client asserted
actor_source    enum       HEADER | BODY | NONE
session_id      text       the tester_session cookie — which browser sandbox
request_id      text       the existing X-Request-Id (main.py:163)
verb            text       POST | PUT | DELETE | GET (GET only for D3's one read)
route_template  text       "/v1/cases/by-customer/{customer_uid}/dc-status", never the raw path
act             text|null  the domain's own name, e.g. DC_STATUS_SET; null when unenriched
subject_type    text|null  customer | case | order | ptp | review | document …
subject_uid     text|null
detail          jsonb      what the domain attached: {from, to, reason, …}
outcome         enum       OK | REFUSED
status          int        HTTP status
error_code      text|null  the Problem `code` when refused
prev_hash       text
hash            text
```

**Refusals are recorded.** An act that was attempted and refused is exactly what an audit trail
exists to show; a log of successes only cannot distinguish "never tried" from "tried and stopped".

**The raw request body is never stored.** Only fields the domain names, through `describe()`.
Bodies carry phone numbers and free text, and this is a store designed never to be deleted from;
a whole-body capture would be a standing data-protection liability acquired by accident. `reason`
is kept, deliberately — it is the point of R14 and of edit 22, and it is named, not swept in.

**`actor_claimed` is never called `actor`.** The pair `actor_claimed` + `actor_source` is the
whole honesty of this log until SSO exists (§1.3). The screen renders it badged (§7).

---

## 5. Immutability

**The chain.** `hash = sha256(canonical_json(entry_without_hash) + prev_hash)` (string concatenation), where
`canonical_json` sorts keys and fixes separators so the same entry always hashes the same. The
first entry's `prev_hash` is a fixed genesis constant. Editing, reordering or deleting any row
breaks every hash after it.

**The guarantees, stated exactly:**

- **Tamper-evident, not tamper-proof.** We hold the credentials. What the chain buys is that no
  alteration can be *silent*.
- `GET /v1/audit/verify` walks the chain and returns the first broken link by `seq`, or a clean
  result with the count verified.
- **No mutation route exists.** Not guarded — absent. There is no `PUT`, `PATCH` or `DELETE` under
  `/v1/audit`.
- The application's DB role is granted `INSERT` and `SELECT` on `audit_entries` and nothing else,
  so even a bug cannot issue an `UPDATE`.
- **Its own table, never the session store.** §1.4's pickle is discarded on deploy by design; an
  audit log in it would be an audit log that a release erases.

**With `DATABASE_URL` unset** the log runs in memory with the same chain and the same verify
endpoint, and every screen that shows it carries a plain statement that the log is not persisted.
This follows `db.py`'s own rule — *RUNNING and REFUSING are both honest, LEAKING is not* — and it
keeps the prototype runnable on a laptop, which is how it is developed and demonstrated.

**When the write itself fails.** The act has already happened; refusing the response would not
undo it, it would only hide it. So: the failure is reported to stderr, a gap counter is
incremented, and `verify` reports known gaps beside broken links. A log that silently drops rows
is worse than one that admits it dropped them.

---

## 6. Capture

**A third HTTP middleware**, registered after `tester_session` so the session and the acting name
are resolved when it runs. It:

1. matches the request against D3's scope — any non-GET, plus the one logged GET — and does
   nothing otherwise;
2. opens a per-request entry in a `ContextVar`, the same mechanism `REQUEST_ID` already uses;
3. lets the route run;
4. fills `outcome`, `status` and `error_code` from the response;
5. appends once, **inside the session token's scope** — the same placement and the same reason as
   `flush_current` (`main.py:195`).

**Domain enrichment.** `audit.describe(act=…, subject=…, detail=…)` attaches business meaning to
the current entry; `subject` is a `(type, uid)` pair and lands in the two columns
`subject_type` and `subject_uid` (§4). It is a no-op outside a request, so domain functions stay callable from tests
and jobs without the log being present. First callers, chosen because they are the acts whose
history is most often asked for:

- `cases.set_dc_status` → `DC_STATUS_SET`, `{from, to, reason}` (already has all three since
  edit 22)
- `cases.set_npl_type` → `NPL_TYPE_SET`
- `cases.log_contact` → `CONTACT_LOGGED`
- the power acts → `POWER_*`
- `routers/integrations.override_order_status` → `R14_OVERRIDE`
- `routers/journey.recovery_board_move` → `RECOVERY_STAGE_MOVED`

Unenriched acts still produce a complete row with `act: null` — the verb and route template say
what happened, which is the floor this design guarantees everywhere.

**This log does not replace the three trails in §1.2.** `reports.py:183` reads `CaseState.events`,
and migrating it is a separate job with its own price. The case timeline stays the case timeline;
this is the record of acts across the whole system. Saying so here so a later reader does not
"finish" a migration that was never started.

---

## 7. The screen

A new route `/audit`, and a tenth rail row in the ระบบ group beside รายงาน, ตั้งค่า and
แหล่งข้อมูล.

- **A verify banner across the top**: chain verified to entry N, or broken at entry N, or — in
  memory mode — the plain statement that the log is not persisted.
- **One row per entry**: time · who · act · subject · from → to · reason · outcome.
- **`who` is badged.** The name renders with a marker meaning *claimed, not authenticated*, and the
  badge explains itself on hover and to a screen reader. This is the §1.3 honesty made visible;
  it is not decoration and may not be removed without SSO.
- **Refusals read as refusals**, carrying their Problem code, never styled as successes.
- **Filters**: actor, act, customer, date range. Served, never client-side — the log will outgrow
  a page.
- **The subject links** to the customer it names, so the log is a way into the work and not only a
  record of it.
- Thai first, and every new string goes in an `i18n-*.js` table where `i18n.test.js` enforces
  EN/TH parity — never `prefs.jsx`'s `DICT`, which nothing checks.

---

## 8. Price

**Backend: additive.** New module, new table, new middleware, new endpoints, new tests. No existing
test asserts the absence of an audit row, and the middleware changes no response body.

**Frontend: one authorised test edit.**

`Shell.test.jsx` asserts the rail's exact contents — `TH_ORDER` (:18), `ROUTES` (:24) and the EN
labels array (:60). A tenth row moves three array literals across two test functions. This is the
identical shape and the identical price as **edit 18**, which added the Dashboard row, and it is
quoted here before it is spent. `App.test.jsx` asserts no route list, so the `/audit` route itself
costs nothing.

**`density.test.jsx` is not affected** — it censuses `CustomerCase`, which this design does not
touch. (Named explicitly because edit 22 was under-priced by exactly this file.)

**Edit 17 stays reserved.**

---

## 9. Not in scope

- **Authentication.** This log records claims. It becomes a record of *people* when SSO lands, and
  the `actor_source` field is the seam that will carry that change.
- **Migrating `CaseState.events`** (§6).
- **Retention and deletion.** An append-only log grows without limit. Nothing here deletes, and
  nothing should until there is a retention rule someone has decided; PDPA erasure against an
  append-only store is a real question and it is not answered by this design.
- **Export.** Reading the log out as CSV would need the governed-export treatment rulings 72/74
  gave the work book, and is its own piece of work.
- **Anchoring the chain externally** (publishing periodic hashes somewhere we do not control),
  which is what would move this from tamper-evident toward tamper-proof.

---

## 10. Acceptance

1. Every one of the 91 acts produces exactly one entry, and so does the one logged read
   (`GET /v1/cases/by-customer/{uid}`, D3) — proven by a test that enumerates the app's own
   routes and asserts coverage, so a route added later without a row fails the suite. The same
   test asserts that no OTHER `GET` is logged, so D3's scope cannot widen by accident.
2. A refused act produces an entry with `outcome: REFUSED` and its Problem code.
3. `verify` reports a clean chain after a run, and names the exact `seq` after a row is altered in
   place.
4. No route under `/v1/audit` accepts `PUT`, `PATCH` or `DELETE`.
5. The screen states, in Thai, whether the log is persisted.
6. `./scripts/verify_all.sh` green at or above the baseline, counts pasted.
