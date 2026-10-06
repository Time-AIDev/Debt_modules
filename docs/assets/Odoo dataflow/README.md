# Odoo dataflow — crm.lead into the book

| | |
|---|---|
| Made | 2026-09-11, for the `crm.lead` pipeline design |
| Made from | **Measurement, not intent.** Every count on these sheets came from `scripts/compare_crm_to_sheet.py` and `scripts/pull_odoo_csv.py` run against Odoo UAT (uid 299, read-only) and the Drive export of the New Order Master. |
| Describes | `docs/archive/superpowers/specs/2026-09-11-odoo-crm-lead-pipeline-design.md` and the rules at `docs/odoo-comparison/odoo_compare.md` |
| Rank | **Not a ranked row on the Amendment v2.6 §1 authority ladder.** A drawing of a design, which is itself below every ranked document. |
| Rebuild | `./src/build.sh` — regenerates all four files from `src/*.py` |

## The two sheets

| File | What it settles |
| --- | --- |
| `00-dataflow` | The two ingress doors, the one raw shape they share, what `normalise()` does, what lands in the landing schema, and what 34,401 rows actually buy |
| `01-rules` | The rules themselves with the evidence for each: which join keys hit, what gets translated, what the 47 columns did, and what the pipeline refuses to land |

Both formats come from the same source and cannot disagree: `.svg` is the one to
embed or edit, `.png` (2× device scale) is the one to paste into a deck or a chat.

## Status — drawn before built, rebuilt after

These sheets were drawn **before** the pipeline existed, on purpose: the dataflow was
easier to argue about as a picture than as paragraphs, and two of the four decisions
on sheet 00 were made by looking at it.

The pipeline shipped on 2026-09-11 and the sheets were rebuilt against the code that
day. Three things they used to claim and no longer do:

| Was drawn | What the code does |
| --- | --- |
| A `join` band inside `normalise()` | `normalise()` has no join. The band now reads `identity` — cleaning `volt_id`, and treating Odoo's literal `"New"` as no id rather than a bad one |
| The overwrite ledger makes precedence auditable | The ledger compares **whole `volt_id` strings**, which the two systems never share, so it reads 0. That is no measurement, not no harm |
| Sheet 01's Rule 1 join keys are applied | They are parsed and consumed by nothing. Marked **NOT YET WIRED** on the sheet |

A sheet must never become a picture of something the code no longer does. The check is
cheap: `src/*.py` names the modules it draws, so a module that moves breaks the
sheet's caption and not just its accuracy.

## Two things on these sheets worth arguing with

**Precedence.** Sheet 00's red note records a decision — Odoo wins — that was taken
knowingly against a recommendation, together with what it costs. The note is on the
diagram rather than in a commit message because the cost lands on customers an
officer is looking at, and the next person to read this should meet the trade-off at
the same moment they meet the design.

**The absence of money.** Sheet 00's right-hand note is the honest ending: all 34,401
rows land as identity and none of them reach Today, arrears or NPL, because Odoo
holds no debt to collect. If a future sheet shows Odoo feeding the collection lists,
something has either changed in Odoo or been invented — and the second is what the
`data_source` badge exists to catch.

## Drawing library

`hld_lib.py` is **imported from `../../HLD/src`, never copied.** One drawing library,
so a change to a tone or an arrow head reaches every sheet the project has rather
than half of them. `src/render.py` holds the whole of that coupling, in two
`sys.path` lines.
