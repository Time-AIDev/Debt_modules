# GCP staging design — sheet by sheet

| | |
|---|---|
| Made | 2026-09-10, from the design approved in the same session |
| Made from | **`docs/archive/superpowers/specs/2026-09-10-gcp-staging-postgres-design.md`** (`a13b5d6`) and the tree at `6ce4d07`. Facts on these sheets are the spec's facts; where a sheet and the spec disagree, the spec is right and the sheet is stale. |
| Rank | **Not a ranked row** on the Amendment v2.6 §1 authority ladder. See "Standing" below. |
| Rebuild | `./src/build.sh` — regenerates all twelve files from `src/*.py` |

## The sheets

| File | Sheet | What it settles |
| --- | --- | --- |
| `00-context` | Context | Who touches the staging environment, what it touches, the four manual steps, and everything deliberately out of scope |
| `01-topology` | Topology | The estate itself — Cloud Run, Cloud SQL, the two Jobs, Scheduler, Secret Manager — and why the native Cloud SQL connector deletes three components |
| `02-data-path` | Data path | Two sources, one landing schema, one seam; the three-rung precedence chain; where Odoo can and cannot reach |
| `03-schema` | Schema | The five tables, their columns, and why `data_source` sits inside the primary key |
| `04-states-and-failure` | States & failure | Configured, unconfigured, unreachable — three states, not two — and what each failure does |
| `05-delivery-and-gaps` | Delivery & gaps | Three waves and six streams, the manual/automated split, and what is deliberately not built |
| `06-one-page` | One page | The whole design on a single canvas — for showing whole, without paging |

Both formats come from the same source, so they cannot disagree: `.svg` is the one to embed or
edit, `.png` (2× device scale) the one to paste into a deck or a chat.

## The emitter is shared, not copied

`src/render.py` imports **`docs/assets/HLD/src/hld_lib.py`** rather than keeping its own copy, so the
two diagram sets cannot drift into different house styles. The only change made to that library was
an optional `right=` argument on `footer()`, defaulting to the HLD set's own label — the HLD sheets
regenerate byte-identically after it.

PNGs are rendered by the headless Chrome for Testing already vendored under `.uat-browser/` for the
UAT rounds. No new dependency was added for any of this.

## Standing — read this before citing it

These sheets describe a **design that has not been built**. At the time of writing **no GCP resource
exists**: `gcloud` on this machine has no credentialed account, and `terraform` and `docker` are not
installed at all.

They carry no rank. Where a sheet and a ranked source disagree, the ranked source wins and the sheet
is wrong — tell whoever is holding it. Their principal input, *Volt Debt — GCP Architecture v1.0*
(Drive `02 GCP`, `1ftWtJ_foJoatoYK7ErRM8Bs0s43HH-LWwjGrWrveGJM`), sits at rank 6 and describes the
**MVP**; these sheets describe a **staging host for UAT**. The differences are deliberate and are
listed on sheet `05` as the gap list.

They are also **dated**. Every count on them — 418 customers, 5 Odoo orders, 158 endpoints, 32
domain modules, 569/443/29 tests — was true on 2026-09-10 and will drift. The counts are written
into the source, not computed, so they must be re-read by hand.
