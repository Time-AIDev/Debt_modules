# Debt Module — Platform Integration Flow

| | |
|---|---|
| File | `debt-module-platform-integration-flow.png` |
| Supplied by | Arina (arina.j@volt.co.th), **2026-09-06**, in the session that opened round 5 |
| Filed | 2026-09-06 by the orchestrator, **with its provenance, deliberately** |
| Rank | **Not a ranked row on the Amendment v2.6 §1 ladder.** See "Standing" below. |

## Why this file has a README

`pictures/debt-flow/` (now `docs/assets/SOP/`) was filed in August under a line describing **how the files arrived**
("exported from Downloads") rather than **what they were** — and they turned out to be the ladder's
**rank-2 four flowcharts**. That misfiling caused a real wrong conclusion in round 4: the
orchestrator reasoned from the README that the diagrams sat at rank 5 and therefore lost a conflict
they should have won. **This file records what this diagram is, and what it is not, on the day it
arrived.**

## What it shows

Three lanes and one loop.

**Odoo** — the lessor self-calculates the instalment schedule → Finance/BU reviews and verifies →
the lessor **freezes** the data once BU confirms → **push frozen data** →
**PEAK** — import contract (number of instalments / amount per instalment) → PEAK generates an
invoice per instalment → *(dashed, i.e. a check rather than a step)* check PEAK API limits and the
required fields held on PEAK →
**Debt Module** — integrate instalment amounts into Debt → show each document in detail with a
**drill-down link back to PEAK** → update the payment record in Debt.

Separately, the payment loop: **customer makes a payment → PEAK sets status = Paid →
webhook · real time → update the payment record in Debt.**

## What is already built, checked at source 2026-09-06

- **The payment webhook exists**: `POST /v1/webhooks/peak/payments` (`backend/app/main.py:883`) —
  *"the WEBHOOK path. Records the transaction unallocated and raises an ACC exception"*. The
  bottom-right loop of this diagram is the shipped behaviour, and it deliberately **never guesses an
  allocation**.
- **The Odoo lane is wired and refused**: `/v1/integrations/odoo/discovery`, `:sync`,
  `:use-snapshot`, `:use-sheet` all exist; the first three return 403/422
  (`integration_not_configured`) and only `:use-sheet` succeeds.
- **PEAK holds two verbs only** — `create_draft` and `read_state` (`integrations/peak.py`). It
  creates **drafts**; a person inside PEAK approves them into the books, and a test fails on a third
  verb. **"PEAK generates an invoice per instalment" is therefore a draft in this product, by
  design.**
- **No file upload exists** anywhere in the backend — no `UploadFile`, no multipart. The sheet
  import is a CLI script (`scripts/import_master_sheet.py`) over a Drive text render.

## Standing — read this before citing it

**This diagram is not a ranked row on the Amendment v2.6 §1 authority ladder** and does not become
one by being filed here. It is **owner-supplied design input for round 5**, and under clause 3a it
binds for what it names about how the flow is SHOWN — never over ranks 1–3 (the 2026-09-01
interview, the Team SOP, Amendment v2.6). **Where it and a ranked source disagree, that is a finding
to raise, not a supersession.** If Arina intends it to rank, that is an amendment she takes
explicitly, and this line should be replaced with the rank she gives it.
