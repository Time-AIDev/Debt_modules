# Spec deltas — the 2026-08-30 rebuild (Amendment v2.5 over the deck v20.0)

| | |
| :-- | :-- |
| Document | What the rebuild changes relative to a v2.4 reading: the new authority ladder, the sixteen rebuild decisions and their code consequences, and the deltas the deck v20.0 forces on the spec line |
| Baseline | Amendment v2.4 over PRD v2.1 (see `spec-deltas-v21-v24.md`, whose deltas all remain in force) |
| Written | 2026-08-30 |
| Covers | Only what DIFFERS from a v2.4 reading. Everything not named here is unchanged |
| Author | Arina (arina.j@volt.co.th) |

## 0. The authority ladder

This ladder supersedes the ladder in `spec-deltas-v21-v24.md` §0.1. It must appear byte-identical in every document that states one.

| Rank | Document | Authority |
| :-- | :-- | :-- |
| 1 | Requirements Amendment v2.5 (rebuild) | Highest, for what it names only |
| 2 | Deck "VOLT ERP — SPV/EPC Scenario Workflows v20.0" | Final authority on scenario workflows 1–12. Its version line (v9→v20) is separate from the spec line (v1.0→v2.x); a larger number on one line says nothing about the other. Where it conflicts with requirement text below and v2.5 has not yet named the conflict, the scenario shape wins and the gap is raised for the next amendment |
| 3 | Requirements Amendment v2.4 | For what it names and nothing above touches |
| 4 | Grilling Session Records (2026-08-30 rebuild; 2026-08-26) | The why, not the what |
| 5 | Case Register v1.3, Runbook Alignment v2.4 | Downstream applications of the decisions |
| 6 | PRD v2.1, Data Model v2.1 + v2.2 delta | Authority for everything not named above |
| 7 | Local repo v1.0 | Baseline, in force only where nothing above touches it |

## 1. The sixteen rebuild decisions and what each does to the code

Full record with options and costs: Drive → 12 Decision Records → "Volt Debt — Grilling Session Record 2026-08-30 — Rebuild".

| # | Decision | Code consequence |
| :-- | :-- | :-- |
| R1 | Month-37 billed either way; decline OPEN (SVC-37, Jo) | Register entry `service_month37_decline_allowed` (RUNNING, default "billed either way"); `:decline` endpoint records the request as 202 and changes nothing |
| R2 | Bilingual TH/EN, Thai default, full coverage | Dictionary split `src/i18n/{en,th}.js`, ~380 new keys, key-parity vitest |
| R3 | Full backend re-architecture around S01–S12 | `app/routers/*` split; new domain modules; the seven `app.main` state globals kept for the conftest seam; 208 existing tests stay green |
| R4 | Drive: new versions + History moves | See the Drive table in the plan; moves executed when each successor publishes |
| R5 | Demo book sheet-derived + synthetic marked | `data_source: ODOO \| SHEET \| SYNTHETIC` on every row, field-grouped (identity vs history); UI marker chip |
| R6 | Ladder shown, NPL manual; `ladder_mode` switch | `app/ladder.py` computes `indicative` only; case stages move by human POST; `ladder_mode: ASSISTED \| MANUAL` per session (MANUAL → `indicative: null`) |
| R7 | Code-first design | `docs/archive/briefs/screens-v2/*` are the design record |
| R8 | UAT apparatus kept | UAT tasks, feedback, `e2e_check.py`, `verify_all.sh` rewritten for the journey |
| R9 | Next-call hero card first | My Day: hero card → tier chips → queue table → board (collapsed) |
| R10 | Guided queue + free override | `next_up` pointer from the API; drawer offers "ถัดไป →"; every row stays clickable |
| R11 | Tiered priority | Sort tiers: (1) PTP due today, (2) largest arrears, (3) deepest ladder step, (4) broken PTP; every item carries `priority_reason` |
| R12 | โทร (tel:) + LINE deep link | `phone_e164` link-only field (display stays masked); `line_id` seeded for demo customers; both actions open the ContactDrawer |
| R13 | Live Odoo sync, discovery-first | `app/integrations/odoo.py`: JSON-RPC; `GET …/odoo/discovery`; `POST …/odoo:sync`; snapshot cache `backend/var/odoo_snapshot.json`; fallback ODOO → cache → sheet fixtures |
| R14 | Local status override + provenance | `{source_value, adjusted_value, by, reason, at}`; re-sync keeps the override, sets `source_changed_since_override` |
| R15 | PEAK full write in UAT | `app/integrations/peak.py`; `POST /v1/invoices/{uid}:issue-peak` → `peak_ref` + QR; failure → `peak_state: UNSENT` |
| R16 | Credentials in `backend/.env` | Gitignored; `/readyz` + `GET /v1/integrations/status` report state; never committed or logged |

## 2. Deltas the deck forces on the spec line

### 2.1 Cash format — Cash 2 and Cash 3 retired

v1.0 said (REQ-MNY-006, quoted in `spec-money-engine.md` §2.6): three cash plans, Cash 3 with a 5% surcharge. Deck v20.0 (Win, 26 Aug): **one format only** — deposit from THB 5,000 scaling with system size, then instalment 2 for the whole remaining balance. Cash 2 (50/50) and Cash 3 (50/25/25 + 5%) are retired **and must come OUT of Debt spec §5.2**. Any test case exercising Cash 2/3 is retired by name in the scenario test doc, not deleted from the module docs.

### 2.2 Acquisition price — 85% → 100% of customer NPV

Changed 25 Aug. Any 85% figure anywhere is stale. The buyback mirrors it: on NPL, EPC pays SPV **100% of the remaining NPV** — no discount, not 90%.

### 2.3 THE TRAP — the NPL ladder is not an aging band set

`ref.aging_bucket` (OPERATIONAL 0/1–7/8–29/30+; LEGACY_LDR 30/45/60/75/90) answers "how old is the arrears" and stays exactly as v2.1 defined it, `band_set_code` and all. The deck's **30/60/90/120 is a different instrument**: a ladder of contractual acts (notice → restructure offer → NPL declaration → assignment) keyed primarily on **missed-instalment count** (30d = 1 missed, 60d = 2 missed), with day thresholds as the calendar mirror. Do not add a band set for it, do not conflate a rung with a bucket, and do not derive a rung client-side. `app/ladder.py` is the single source; its `SOURCE` attribute cites the deck.

### 2.4 New shapes with no v1.0/v2.1 ancestor

Invoices and receipts (journey states, OD-02-preserving), PTPs as entities, collection cases (lease + cash ladders), restructures as superseding schedules, NPL cases + assignment deeds, recovery cases + repossession lots (count-based, A/B/C, `PANEL-550-R` @ `WH/REFURB`, Dan's price unblocks), service billing accounts (prepaid window, month-37 counter, 399 floor, 25th–30th window, own dunning, never feeds lease NPL), manager reviews + arrangement plans, service issues, cancellation cases (cause test), inter-company documents (S10 ledger; the THB 50,000 fee refuses to post — manual, outside the ERP). Data Model v2.2 (Drive) is the schema record; **the prototype is again the first place these exist**.

### 2.5 Allocation stays refused

Receipts recorded by the journey move invoice/journey state and are stored `is_allocated: false` with an exception raised while OD-02 is open — the same asymmetry the PEAK webhook already has. `money/allocation.py` is untouched.

## 3. Configuration added by this rebuild

| Key | Value | Register state |
| :-- | :-- | :-- |
| `service_month37_decline_allowed` | undecided — billed either way | RUNNING · SVC-37 · owner Jo |
| `service_monthly_floor_thb` | 399 | config, deck v20.0 |
| `service_billing_window` | 25th–30th | config, deck v20.0 |
| `acquisition_pct_of_npv` | 100 | config, deck v20.0 (was 85, 25 Aug) |
| `uninstall_fee_thb_per_watt` | 5 | config, deck v20.0 |
| `cash_deposit_floor_thb` | 5000 | config, deck v20.0 |
| `discount_rate_effective_annual` | 15.00 EA | OQ-31 flips LEAKING → RUNNING: declared, flagged, used by NPV on deeds/sale invoices |
| `npl_dpd_threshold_days` | still None | OD-04 stays LEAKING; `surfaces_as` names both surfaces (band literal + "90, deck v20.0, indicative only — a human flags") |
| `ladder_mode` | ASSISTED (default) \| MANUAL | per-session preference (R6) |

## 4. Traps and stale text

- **`spec-money-engine.md` §2.6** quotes retired cash plans as live requirement text — the banner on that file now points here; a reader building from it alone would implement Cash 2/3.
- **`spec-api-and-board.md`** and the four `figma-*` briefs document the pre-rebuild screens; they are the record of Figma "Product UI v0.1", not build targets.
- The deck's own STILL-OPEN item (month-37 decline) is easy to mistake for decided because the deck bills either way — the billing is decided; **the right to refuse is not**.
- The deck says NPL is "declared at 90 days"; do not encode that as automation. Declaration is a role-gated human act; the 90 is the indicative rung's source (OD-04's own note: a human flags).
