# Use cases — who may do what, and the guard that decides

| | |
|---|---|
| Made | 2026-09-20, on request |
| Made from | **The running tree** — `auth.ROLES`, the role gates in `routers/` (reviews, power restrictions, assignments, NPL, restructures, payments, exports, pipelines), the lens routes in `frontend/src/lib/nav.js`, and the refusals the endpoints serve. HEAD `dbab955` plus that day's uncommitted work. Not from the deck. |
| Rank | **Not a ranked row on the Amendment v2.6 §1 authority ladder.** A drawing of the build; the endpoints it names are themselves the lower-ranked sources. |
| Rebuild | `./src/build.sh` — regenerates all four files (2 sheets × SVG + PNG) from `src/*.py` |

## The two sheets

| File | What it settles |
| --- | --- |
| `00-use-case-overview` | The UML picture: five human actors, four system actors, one system boundary, 31 use cases, primary-actor associations, and the three `«include»` edges routed through the row gaps so no dashed line cuts a bubble |
| `01-use-case-register` | One row per use case: primary actor, shared roles and guard, entry point, and what it writes — the detail the diagram deliberately omits |

`.svg` is the one to embed or edit; `.png` (2× device scale) is the one to paste into
a deck or a chat.

## How to read the two sheets together

A line on sheet 00 means **the actor may start the use case**, not that every call
succeeds. The guard column on sheet 01 decides each time, and a refusal renders
verbatim from the RFC 9457 envelope (`code` · `message_th` · `errors[]`). The badges
on sheet 00 name the roles a use case is shared with; sheet 01 carries the full list.

## The thing the diagram exists to make visible

The role model is **five values**: `OFFICER · SUPERVISOR · MANAGER · OWNER · OPS`.
Almost every act is available to the officer; the exceptions are the governed acts —
answering a review, approving a power restriction, releasing an invoice and recording
a slip, declaring NPL, approving a restructure, closing a write-off, publishing an
edition, configuring policy, simulating PEAK — and each one names its role at the
bubble. A use-case diagram that drew every line to every actor would hide exactly the
thing this one is for.

**What is deliberately absent from sheet 00:** personal calendar notices, attachments,
and the read-mostly intercompany and cancellation views — noted on the register. The
`«include»` edges are only the three that carry an architectural meaning (one intent,
one local PEAK record); "every use case includes Sign in" is a note, not 31 lines.

## Standing — read this before citing it

This is a **description of the prototype as built**, not a specification of what
should be built. It carries no rank. Where a sheet and a ranked source disagree, the
ranked source wins and the sheet is wrong — tell whoever is holding it.

It is also **dated**: roles, gates and entry points were read from the tree on
2026-09-20 and will drift. Re-render after a structural change; the use-case list is
written into `src/d00_use_cases.py`, not computed, so it must be re-read by hand.

## Drawing library

`hld_lib.py` is **imported from `../src`, never copied** (the same rule the dataflow
set follows). The UML primitives added for this set — the ellipse and the stick-figure
actor — are additive; the six original HLD sheets render unchanged.
