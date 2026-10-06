# High-level design — layer by layer

| | |
|---|---|
| Made | 2026-09-09, on request, in the session that opened after round 6 |
| Made from | **The running tree at `e3b4a19`** — routes counted out of `backend/app/`, screens and components listed out of `frontend/src/`, deploy steps read out of `scripts/` and `infra/`. Not from the deck, not from the document set. |
| Rank | **Not a ranked row on the Amendment v2.6 §1 authority ladder.** See "Standing" below. |
| Rebuild | `./src/build.sh` — regenerates all twelve files from `src/*.py` |

## The six sheets

Each layer is its own file, so a sheet can be shown on its own without the others
having to be cropped away.

| File | Layer | What it settles |
| --- | --- | --- |
| `00-context` | L0 | Who touches the system, what it touches, and the four refusals that shape everything else |
| `01-client-layer` | L1 | Eleven screens, 26 shared components, one fetch client, and the edge (vite proxy in dev, same origin deployed) |
| `02-api-layer` | L2 | The 158 endpoints, where they live, and the three middlewares every request passes through |
| `03-domain-layer` | L3 | All 32 domain modules in four groups, and the laws that outrank convenience |
| `04-data-and-state` | L4 | The four-rung fallback chain, the `data_source` marker, per-session in-memory state, and what actually gets written |
| `05-runtime-and-deployment` | L5 | Laptop, UAT round, Google Cloud — and the terraform that is deliberately unapplied |

Both formats are produced from the same source, so they cannot disagree: `.svg` is
the one to embed or edit, `.png` (2× device scale) is the one to paste into a deck
or a chat.

## Two sub-sets, added 2026-09-20

| Folder | Sheets | What they show |
| --- | --- | --- |
| `dataflow/` | 5 (levels 0–2) | The data itself: terminators, the three intake doors and the one landing shape, the desk's processes, recovery/reports/audit, and the money engine opened up. Rebuild `dataflow/src/build.sh` |
| `use-case diagram/` | 2 | Who may do what: the UML overview (actors, boundary, 31 use cases, `«include»` edges) and the register (roles, entry points, writes, guards). Rebuild `use-case diagram/src/build.sh` |

Both import `src/hld_lib.py` — never copy it. This README's six sheets are unchanged
by it; the DFD and UML primitives the sub-sets needed were added, not modified.

## Eraser

`src/eraser/*.eraser` holds the same six diagrams as **Eraser diagram-as-code**,
one file per layer, ready to paste into a new cloud-architecture diagram at
eraser.io. They are the shareable source; they are **not** what produced the images
here.

**Why not:** this machine has no Eraser CLI and no `ERASER_API_KEY`, and Eraser's
render API needs a token. Rather than hand back nothing, the SVG/PNG were rendered
locally — `src/hld_lib.py` emits the SVG, headless Chrome (the one already vendored
under `.uat-browser/` for the UAT rounds) turns it into PNG. Supply a token and the
`.eraser` files re-render through eraser.io without being rewritten.

The repo already refers to an `eraser-diagrams.md` in the Drive document set
(`docs/01-architecture/` in the specs repo, cited in `docs/archive/briefs/spec-money-engine.md:25`). **These six
sheets have not been reconciled against that document** — if it holds diagrams that
contradict these, that is a finding to raise, not a supersession either way.

## Standing — read this before citing it

This is a **description of the prototype as built**, not a specification of what
should be built. It carries no rank. Where a sheet and a ranked source disagree, the
ranked source wins and the sheet is wrong — tell whoever is holding it.

It is also **dated**. Every count on it (158 endpoints, 32 modules, 26 components,
11 screens, 198 customers) was true of the tree on 2026-09-09 and will drift. Rerun
`src/build.sh` after any structural change; the counts are written into the source,
not computed, so they must be re-read by hand.
