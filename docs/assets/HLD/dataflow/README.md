# Dataflow — the prototype's data, four levels down

| | |
|---|---|
| Made | 2026-09-20, on request |
| Made from | **The running tree** — `main.py`'s middleware and router mounts, `book_source.py`, `pipelines/`, `money/`, `audit.py`, the routers, and the lens routes in `frontend/src/lib/nav.js`. HEAD `dbab955` plus that day's uncommitted work. Not from the deck. |
| Rank | **Not a ranked row on the Amendment v2.6 §1 authority ladder.** A drawing of the build, below every ranked document it draws. |
| Draws | The same tree as `docs/assets/HLD/` (the layer sheets) and `docs/assets/Odoo dataflow/` (the intake detail). Where a sheet and the code disagree, the code wins — tell whoever is holding the sheet. |
| Rebuild | `./src/build.sh` — regenerates all ten files (5 sheets × SVG + PNG) from `src/*.py` |

## The five sheets

| File | Level | What it settles |
| --- | --- | --- |
| `00-level-0-context` | 0 | The system as one process and its five terminators — including the local Postgres, drawn honestly as an optional run mode |
| `01-level-1-intake-and-book` | 1 · 1.0–3.0 | Sign in, the three doors that land rows, and the one shape they all write; stores D1–D3 |
| `02-level-1-collections` | 1 · 4.0–8.0 | Money computed at read time, the seven-tier queue, contacts and promises, decisions, and the PEAK documents they originate |
| `03-level-1-books-outputs-and-audit` | 1 · 9.0–13.0 | Recovery, reports and exports, settings, the middleware audit chain, and the shell |
| `04-money-engine-detail` | 2 · 4.0 | Process 4.0 opened up: seven sub-processes from the served schedule to the indicative ladder rung, and the config register that gates them |

`.svg` is the one to embed or edit; `.png` (2× device scale) is the one to paste into
a deck or a chat. Both come from the same source and cannot disagree.

## Three claims these sheets make on purpose

**One seam, and nobody downstream knows the door.** `book_source.load()` returns the
same shape whether the rows came from the landing schema or the held fixture, so the
32 domain modules and 158 endpoints never learn where the book came from. That is why
sheet 01 draws three doors writing one store and one process reading it.

**No money table.** Every figure — DPD, arrears, outstanding, penalty accrued-unbilled,
the payment position, the ladder rung — is a function of (book, transactions, config,
business date) evaluated at read time. Sheet 04 draws the whole pass, and there is no
write arrow into any figure. Change the date and everything re-derives.

**The audit chain is not a feature.** Middleware appends one hash-chained entry per
non-GET request; no endpoint writes it, so no endpoint can forget to. Sheet 03 draws
it as a bus across the acts rather than one process among many.

## What the sheets refuse to hide

The open decisions ride on the pictures: CF1 (late-fee rate), OD-02 (allocation
order), OD-04 (NPL threshold), OQ-31 (discount rate) and SVC-37 (month 37) each sit
on the arrow they gate, and an indicative ladder rung is badged as indicative. The
refusal notes are part of the diagrams, not a footnote: a sheet that shows a guess
without its badge is wrong even when the guess happens to match the eventual ruling.

## Drawing library

`hld_lib.py` is **imported from `../src`, never copied.** One drawing library, so a
change to a tone or an arrow head reaches every sheet the project has rather than
half of them. The two `sys.path` lines in `src/render.py` are the whole of the
coupling. The DFD primitives added for this set (the data store, the numbered
process) are additive: the six original HLD sheets render unchanged.
