# Odoo `crm.lead` pipeline — design

| | |
|---|---|
| Date | 2026-09-11 |
| Status | **Built and running.** §1 of the rules file (the join) and §6's registry filter are not. §12 lists every gap between this document and the code |
| Rules | `docs/odoo-comparison/odoo_compare.md` — parsed at runtime, not restated here |
| Diagrams | `pictures/Odoo dataflow/` — `00-dataflow`, `01-rules` |
| Plans | `docs/archive/superpowers/plans/2026-09-11-odoo-crm-lead-pipeline.md`, then `…-import-data-progress-and-schedule.md` |
| Evidence | `scripts/compare_crm_to_sheet.py`, run 2026-09-11 against 58 `"x"` rows and 34,401 `crm.lead` rows; then a live pipeline run against 34,338 leads |
| Rank | Not a ranked row on the Amendment v2.6 §1 authority ladder. It implements what the ladder already says; where it and a ranked document disagree, the ranked document wins. |

## 1. What this is for

An officer wants Odoo's `crm.lead` in the book, and wants to choose how it gets
there: drop a file exported from the sheet's `"x"` tab, or pull from Odoo directly.
Both doors already half-existed — `imports.py` took an upload and staged it without
installing (rulings 71/73), `integrations/odoo.py` pulled and wrote to landing — and
neither knew anything about `crm.lead`, which the 2026-09-11 census identified as
the Odoo counterpart of the `"x"` tab.

**What this design is not:** it is not a claim that the prototype's data comes from
Odoo. After it shipped, the book's 198 customers are still the sheet's, and the
34,203 Odoo rows a live run landed carry no money — every one of them is an identity
with `reason = "no money row in Odoo"`.

## 2. The decisions this design encodes

The first four were put as questions on 2026-09-11 and answered before any code:

| Decision | Chosen | Alternative rejected |
|---|---|---|
| Output | Rows in the landing schema, badged ODOO | report-only; cleaned dataset; stage-then-approve |
| Rules | Drafted from the measured comparison into `odoo_compare.md`, reviewed | rules in code; wait for hand-written rules |
| Row filter | **All 34,401**, filtered in the UI | won/signed only; volt_id only; overlap only |
| Precedence | **Odoo wins** — `landing._PRECEDENCE` unchanged | field-level with sheet owning money; sheet always wins |

Two more were settled during the build:

| Decision | Chosen | Note |
|---|---|---|
| Refetch schedule | **15 minutes, off until switched on**, in-process only | Enabling does not fire a run; the timer stamps `last_run_at` before the run, not after, so a slow run cannot queue a second |
| Rail label | **"Import Data"** / **"นำเข้าข้อมูล"** | Reverses ruling 70 ("the rail keeps the SOP's word") on this row, at the user's explicit instruction, asked twice. Recorded as their ruling, not as a drift |

Rows 3 and 4 of the first table were chosen against the recommendation, knowingly.
§7 records what they cost and how the cost was meant to be made visible — and §12
records why that visibility does not yet work.

## 3. Components

Nine backend units and three frontend ones, each with one job.

| Unit | Depends on | Job |
|---|---|---|
| `docs/odoo-comparison/odoo_compare.md` | — | The rules, as markdown tables |
| `backend/app/pipelines/rules.py` | that file | Parse it into a `Rules` object. No Odoo, no DB, no I/O beyond the read |
| `backend/app/pipelines/crm_lead.py` | `rules` | `normalise(rows, rules) -> (records, verdicts)`. Pure: same input, same output, no clock, no network |
| `backend/app/pipelines/ingress.py` | `odoo`, `imports` | `from_odoo(rules, …)` and `from_upload(raw, filename, rules)`, both returning the same `list[dict]` |
| `backend/app/pipelines/writer.py` | `landing` | One `import_run` of source ODOO, batched 1,000, plus the overwrite ledger |
| `backend/app/pipelines/runs.py` | — | A process-wide run registry, newest 20 kept. `elapsed_seconds` freezes when the run finishes |
| `backend/app/pipelines/service.py` | all of the above | **The run sequence, once.** The button calls it, the timer calls it, a test calls it |
| `backend/app/pipelines/schedule.py` | `service` | A daemon thread polling every 5s, firing every 15 minutes when enabled |
| `backend/app/routers/pipelines.py` | `service`, `runs`, `schedule` | Six endpoints, Manager-only (§11) |
| `frontend/src/components/DropZone.jsx` | — | A drop target wrapped **around** a real `<input type="file">` |
| `frontend/src/components/RunProgress.jsx` | — | A bar that makes no claim until the run reports a total |
| `frontend/src/screens/DataSourcesMigration.jsx` | both | The intake desk (§10) |

`rules.py` and `crm_lead.py` between them are the whole of the domain logic, and
neither touches a socket or a database — which is what made the rule tests cheap
enough to write first.

`service.py` exists so that the button and the timer cannot drift apart. A second
copy of the sequence for the scheduler would be ruling 36's second-pattern MAJOR on
the one sequence that matters.

## 4. The two doors

Both adapters return an identical list of raw dicts, so `normalise()` cannot tell
which ran. That is the seam that makes "the officer picks one" a UI concern rather
than a domain one.

**Direct pull.** `search_read` on `crm.lead`, paged 500, `order: "id"`, requesting the
fields named in §2 of the rules file. The field list comes from the rules, not from a
constant in the code, so adding a column to the map adds it to the pull.

**Drag and drop.** `imports.decode_csv` and `imports.read_xlsx`, imported. A second
CSV parser would be ruling 36's second-pattern MAJOR, and the existing one already
handles the xlsx traps — shared strings, date serials, the 1904 epoch — that a
hand-rolled reader gets wrong on the first Thai export it meets.

**Upload shape.** Raw body plus an `X-Volt-Filename` header, matching
`routers/imports.py`. The first draft of the plan specified `UploadFile`; the repo
has no `python-multipart`, and adding a dependency to avoid reading the neighbouring
router was the wrong trade.

## 5. Data flow

```
                 ┌── drag and drop ──┐
raw rows ────────┤                   ├──▶ normalise(rows, rules) ──▶ landing ──▶ book_source.load()
                 └── pull from Odoo ─┘              │                   │
                                                    │                   └─ one import_run, source ODOO
                                          map · vocab · dates ·            row_counts · rejected+rule
                                          codes · verdict                  overwrite ledger
```

Drawn in `pictures/Odoo dataflow/00-dataflow.svg`. **That sheet's `join` band is
ahead of the code** — see §12.

One `import_run` per run, one transaction. A failure leaves the previous run's rows
serving, which is `sheet_loader`'s existing contract and the reason `_ok_runs_clause`
filters on `status = 'OK'`.

## 6. Volume

34,401 rows is ~170× today's 198-customer book. Three consequences:

**Writing.** `landing.write_customer` one statement per row would be 34k round trips.
Written in chunks of 1,000 inside the run's single transaction, reporting progress
after each chunk. **Built.**

**Building.** `main.py:80` builds the book once at process start, not per request, so
this is a boot cost rather than a per-request one. Every Odoo row is identity-only —
no money row means no contract, no amortisation schedule — so the marginal cost is a
dict per row. **Built, not yet measured** against a full 34k book; if boot moves by
more than a few seconds the fix is lazy identity rows, and that is a follow-up.

**Reading.** 34k identity rows would swamp any list that shows the book. They land
with `data_source = ODOO` and `reason = "no money row in Odoo"`, and this design
promised the Data sources screen a filter so an officer could see them deliberately
rather than by accident. **Not built** (§12). No existing list changed its default,
so nothing currently shows them by accident either — but nothing shows them on
purpose yet.

## 7. Precedence, and the ledger that was meant to pay for it

`landing._PRECEDENCE` already puts ODOO ahead of SHEET, and stays as it is.

That was harmless while Odoo contributed 5 rows that touched no sheet customer. With
34,401 it overlaps: 58 of 58 sheet rows matched a lead by phone. So on an overlapping
customer a **blank or zero in Odoo now replaces a real sheet value**, and
`energy_bill`, `inverter_kw` and `monthly_rate` are 0 on every Odoo row measured.

The rule is not re-argued. Its cost was to be made visible: every replaced value
written to an **overwrite ledger** on `import_run.meta` carrying `volt_id`, field,
sheet value and Odoo value.

**The ledger is built and it reports nothing.** `writer._sheet_rows` finds the sheet
rows to compare against by **exact `volt_id`**, and the two systems do not hold the
same string — the sheet's long form is `<crm id>_<name>_<epc>`, Odoo's is `99999000206`.
So the comparison matches almost nothing and every run so far has reported
`overwrote 0`. That is not evidence the precedence rule is harmless; it is the
absence of evidence either way. §12 carries the fix and the two ways to take it.

## 8. Error handling

| Situation | Behaviour |
|---|---|
| Rules file missing or a table malformed | Refuse the run, naming the table and the line. Never fall back to a built-in default — a pipeline running on rules nobody can see is the whole problem |
| Odoo unreachable mid-pull | Run recorded FAILED with its problem; previous run keeps serving; no partial landing |
| A field Odoo refuses to read in batch | Named in the run report, the rest of the model still lands — the behaviour `scripts/pull_odoo_csv.py` already proved necessary |
| Upload over **25 MB**, or not csv/xlsx | Refused by `imports.py`'s existing guards. The cap was 5 MB and was raised for this pipeline; the message interpolates `MAX_MB` rather than naming a number that can go stale |
| A zip that inflates past 200 MB | Refused before it is trusted |
| A value with **no §3 translation** | Passed through — title-cased if it is snake_case — AND recorded as unmapped, so a missing rule is visible rather than silent |
| A field with no rows in §3 at all | Passed through, not flagged. Nothing claims to translate it |
| Row rejected by §5 | Counted with the rule that rejected it |
| A run that dies in a background thread | `runs.fail()` with the exception's class and message. A thread has nowhere to raise to; leaving the run "running" for ever is the failure mode being prevented |

Nothing in this table falls back silently. `db.py` already states the principle:
running and refusing are both honest, leaking is not.

## 9. Runs, progress, and the timer

Added after the original design, on the user's instruction ("show a progress bar and
elapsed time counter; if Odoo is chosen, set a 15-minute refetch schedule").

**The registry.** `runs.py` holds the newest 20 runs in process memory. A run carries
`state`, `read`, `total`, `landed`, `rejected`, `elapsed_seconds` and, if it failed,
its `problem`. `elapsed_seconds` is computed from the clock while running and frozen
at `finish`, so a finished run does not keep ageing.

**The bar.** `RunProgress.jsx` carries **no `aria-valuenow` until `total` is known**.
An indeterminate bar that pretends to be at 30% is worse than one that admits it does
not know. A failed run shows its reason instead of a bar frozen where it stopped.

**The timer.** Off until switched on. `INTERVAL_DEFAULT = 15` minutes, polled every
5s. `state()` reports `in_process_only: True` — with N instances the timer would fire
zero times or N times, so the flag is the honest label rather than a claim of
cluster-wide scheduling. Enabling does not fire a run.

## 10. The screen

Reworked twice: once to remove duplication, once as a design pass ("the intake
desk — a custody transfer with a receipt"). Built inside the existing Kanit /
JetBrains Mono system with no new palette; `journey.css` is tokens-only and
`journey.test.js` enforces it.

- **A provenance strip** naming the serving rung **before** its counts. A number with
  no origin is the one thing this product refuses to print.
- **Three numbered steps.** Numbering is usually decoration; here the content is
  genuinely a sequence, because a receipt cannot exist before the act.
- **Two source cards, each stating its own cost** — `.csv/.xlsx · up to 25 MB`
  against `~34,000 leads · about 1.5 minutes`. An option that hides its cost is a trap.
- **A permanent manifest** holding the empty state, then the live bar, then the final
  counts in mono tabular figures. It costs vertical space and buys knowing in advance
  what you will be told.
- **The browser's `Choose File` chrome is hidden**, not the input. The input keeps its
  type, its tab position and its place in the accessibility tree, with an explicit
  `aria-label` — the wrapping `<label>` also contains the hint line, so its text
  content would have named the control "choose a sheet file drag a file here or click
  to choose".
- **Ruling 71's `import-report-live`** renders inside step 3, where the act happened.
- The older `ซิงก์จาก Odoo` control and the rung detail are collapsed into `ขั้นสูง`.
  Collapsed, not retired — see §12.

## 11. The API

All Manager-only; a non-Manager gets `DEBT-IAM-0403`.

| Endpoint | Does |
|---|---|
| `POST /v1/pipelines/crm-lead:run` | Runs synchronously, returns the result |
| `POST /v1/pipelines/crm-lead:start` | 202 + `uid`, runs in a thread |
| `GET  /v1/pipelines/crm-lead/runs/{uid}` | One run's state, for the bar |
| `GET  /v1/pipelines/crm-lead/last-run` | The newest run |
| `GET  /v1/pipelines/crm-lead/schedule` | `enabled`, `interval_minutes`, `last_run_at`, `in_process_only` |
| `PUT  /v1/pipelines/crm-lead/schedule` | Turn it on or off |

`:run` and `:start` share `_read_source()`, so the two doors are decided in one place.

## 12. What these documents claim that the code does not do

Kept as a list rather than fixed quietly, because the rules file and the diagrams are
meant to be readable as the truth about the system.

1. **§1 of the rules file — the join — is parsed and never used.** `rules.joins`
   is loaded correctly and consumed by nothing. `writer._sheet_rows` matches on exact
   `volt_id` only, which is why §7's ledger reads 0 (and why measured key 3,
   `volt_exact`, was recorded at **0 of 58**). Two ways to close it, and they are not
   equivalent: mark §1 *measured, not yet applied* and redraw sheet 00's `join` band —
   which makes the documents true in about twenty minutes and changes nothing — or
   feed `rules.joins` into `_sheet_rows` so the ledger compares on phone and stem,
   which changes what a run does to the book. **Awaiting the user's decision.**
2. **§6's registry filter is not built.** The Odoo rows land and there is no
   deliberate way to look at them.
3. **Sheet 00 of the dataflow diagram** shows a `join` band inside `normalise()`.
   `normalise()` has no join; the sheet is drawn to item 1's second option.
4. **§13's testing item 3 was never written**, because there is no join to test.

## 13. Testing

TDD, against the repo's 569/443/29 contract. Written in this order:

1. **Rules parsing** — each table; a malformed table refuses; an unknown column refuses.
2. **normalise(), per rule** — one test per §3 translation, per §4 shape, per §5 rejection, and the `Watt` kW→W scaling.
3. ~~**Join** — the six keys at their measured hit rates.~~ **Not written; there is no join (§12).**
4. **Precedence + ledger** — an Odoo value over a sheet value lands the Odoo value AND writes a ledger row. Passes against a fixture where the two `volt_id`s are equal, which real data is not (§7).
5. **Ingress** — `from_upload` against a fixture csv and xlsx; `from_odoo` against a faked `_execute`, asserting paging and that the field list came from the rules.
6. **Landing** — batching writes the same rows as one-at-a-time; a mid-run failure leaves the previous run serving.
7. **Runs, service, schedule** — elapsed freezes on finish; every exit reaches the registry; enabling does not fire; a slow run cannot queue a second.
8. **Router** — both doors, Manager-only, 202 + uid.
9. **e2e** — a run lands rows badged ODOO and `engine_book` stays 198.

As built: **68 backend tests** across eight `test_pipeline_*.py` files, plus
`DropZone.test.jsx`, `RunProgress.test.jsx` and `DataSourcesMigration.test.jsx` on
the frontend. Full suite green at the last commit: frontend 533, backend suite,
e2e 31/31.

## 14. What the first live run changed

Four things that 34,338 real leads found and no fixture would have:

| Found | Fix |
|---|---|
| Odoo sends `False` for empty and floats for numbers; every test had passed strings. The run died on `re.sub` with a float | Coerced once in `_text()`, not at seven call sites |
| 23,514 of 34,338 leads carry the literal `"New"` in `volt_id`. Rejecting it as unshaped threw away 70% of the book over a value that was never an identifier | Treated as **no** id — the lead still lands keyed by phone. Two real shapes were being refused too: VRL/VRC and the bare 11-digit CRM id. **Landed went 10,413 → 34,203** |
| `translate()` flagged only snake_case, so the run reported **zero** unmapped across 34,336 leads — which read as complete coverage and was a hole | Any unlisted value is flagged. Twelve real `crm.stage` values surfaced and are recorded in §3 of the rules file, deliberately untranslated: they are pre-sale stages the sheet has no Order Status for, and coining one would invent a status nobody set |
| `Watt` was mapped to `panel_watt` — one panel, 710 W. The system size is `inverter_kw` | Remapped, scaled ×1000 |

## 15. Build order, as it happened

Rules doc → `rules.py` → `normalise()` → ingress → writer with batching → router →
the drop zone → the live-run fixes → registry, progress and the timer → the screen.

```
62d21d1  feat(pipelines): one endpoint, either door, Manager only
18674d4  feat(data sources): drag and drop, wrapped around the file input
653c878  fix(pipelines): three things only a run against 34,336 real leads could find
ffd6962  test(e2e): a pipeline run adds identities and no collectable balance
671f489  feat(data sources): the officer picks the door, and the run says what it refused
72c21ca  feat(pipelines): a run you can watch, reporting progress the work actually made
3a48e43  feat(pipelines): one run sequence, and a 15-minute timer that is off until asked
24634b4  feat(pipelines): start a run, watch it, and turn the refetch on
7f3de04  feat(import data): a bar that only claims what the run reported, and a 15-minute refetch
34df043  refactor(import data): one panel, one button, and the rail names the act
9e4df6f  design(import data): the intake desk — a custody transfer with a receipt
```

## 16. Not built, and what it would take

| Item | Why it matters | Size |
|---|---|---|
| Wire `rules.joins` into `writer._sheet_rows` | §7's ledger is the only instrument measuring the precedence decision, and it currently reads 0 for the wrong reason | Changes what a run does; needs the user's word |
| The registry filter (§6) | 34,203 landed identities with no deliberate way to view them | A screen-level filter on `data_source` |
| Cloud Run memory | The 512 MB default will OOM at the new 25 MB upload ceiling | One flag in `scripts/deploy_gcp.sh` |
| Cloud Scheduler | `scripts/deploy_gcp.sh:142` still runs nightly at 02:00 against the **old** `sale.order` sync, not this pipeline | Repoint or retire |
| The old `ซิงก์จาก Odoo` control | Collapsed into `ขั้นสูง`, not retired. Two controls still exist for one job | Decide: relabel or remove |
| Boot cost at 34k rows | §6 promised a measurement that has not been taken | Measure, then decide on lazy identity rows |
