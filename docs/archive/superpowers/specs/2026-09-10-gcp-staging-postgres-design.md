# Design — GCP staging environment, Cloud SQL Postgres, and the sheet-shaped landing schema

**Written 2026-09-10** through `superpowers:brainstorming`, against the tree on branch
`design-team` at `6ce4d07`. Every decision below was ruled on by Arina in that session and is
attributed inline. **Nothing here has been built, and no GCP resource has been created.**

---

## 0. Standing

This document is a **design for a staging environment**, not a specification of the product. On
the Requirements Amendment v2.6 §1 ladder it carries no rank of its own.

Its principal input, **"Volt Debt — GCP Architecture v1.0"** (Drive `02 GCP`, id
`1ftWtJ_foJoatoYK7ErRM8Bs0s43HH-LWwjGrWrveGJM`, 2026-08-21), sits at **rank 6** —
"Integration and Runbook alignments". Where this design departs from it, the departure is named
and justified in §7, never silent. Where the two disagree on fact, v1.0 describes the **MVP** and
this describes a **staging host for UAT**; they are not competing for the same job.

`pictures/HLD/` is a description of the prototype as built, dated 2026-09-09, and likewise carries
no rank.

---

## 1. The problem

Three things are true of the tree today, and all three were verified by reading it, not assumed.

**There is no database.** `sqlalchemy>=2.0` sits in `backend/requirements.txt` and is imported
nowhere. The book is parsed at seed time from `backend/app/fixtures_sheet.json` (418 customers,
produced by `scripts/import_master_sheet.py` from the *New Order Master* sheet) and
`backend/app/fixtures.py`. All 158 endpoints compute over that in-memory structure.

**Tester state does not survive a restart.** `backend/app/session.py` keys mutable state — approvals,
board moves, added and removed orders, saved criteria — by a `volt_session` cookie in a
process-local dict. Its own docstring concedes the consequence: *"It is not persistence. State
still lives in memory and a restart clears every session. Cloud Run will restart. Testers must be
told."* `scripts/deploy_gcp.sh` repeats the warning in its deploy banner. This is the defect that
has shaped every blind UAT round, and it is the one this work exists to kill.

**The Odoo sync writes to ephemeral disk.** `backend/app/integrations/odoo.py` caches its pull to
`backend/var/odoo_snapshot.json`. On Cloud Run that file dies with the revision, so the middle
rung of the `ODOO → SNAPSHOT → SHEET` fallback chain does not exist in the deployed environment
at all.

Against that, `infra/terraform/` (654 lines across ten files) already describes a full stg/prd
estate — and `infra/terraform/versions.tf:3-5` states plainly that **none of it has ever been
applied**: *"NOTHING HERE HAS BEEN APPLIED. No gcloud credentials exist in this environment; these
files are `terraform fmt`-clean and structurally complete, not proven against the API."*

---

## 2. Goal, and what is deliberately not the goal

**Goal.** A staging environment on GCP where the Debt team can run a UAT round against the real
book, where a revision restart does not destroy a tester's morning, and where Odoo data arrives
through the same schema the sheet arrives through.

**Not the goal**, each ruled out explicitly:

- **Production.** Arina: *"prepare environ for staging, not real production."* §15.1 of GCP
  Architecture v1.0 owns the promotion sequence and is not in scope.
- **The Data_Model twelve schemas** (`ref`, `iam`, `config`, `intake`, `restricted`, `money`,
  `collections`, `modifications`, `accounting`, `documents`, `audit`, `kpi`). That is the MVP —
  8–10 weeks per A-01 — and building it would force open decisions the prototype deliberately
  refuses (CF1, OD-02, OD-04, OQ-31, SVC-37). Rejected by Arina in favour of a landing schema.
- **Re-opening the domain.** The 32 domain modules, the seven-tier Today order, the money engine
  and the refusals stay exactly as they are.
- **The full §4–§9 estate.** VPC, NAT, LB, Cloud Armor, Memorystore, Pub/Sub, Cloud Tasks,
  KMS/CMEK and Identity Platform are not built. §7 lists each with what adding it would take.

---

## 3. Decisions taken

| # | Decision | Ruled |
|---|---|---|
| D1 | Postgres holds **the landing schema and per-tester session state**. The domain keeps computing in memory from a book loaded out of Postgres. | Arina, 2026-09-10 |
| D2 | **"Sheet X" is *New Order Master*** — Drive id `SYNTHETIC-SPREADSHEET-ID`, owner `daniel@volt.co.th`. Its shape is derived from the live `fixtures_sheet.json`, not guessed. This closes the placeholder the round-6 plan flagged on 2026-09-08. | Arina, 2026-09-10 |
| D3 | **Sheet baseline + Odoo overlay.** Landing is seeded from the sheet; the Odoo sync writes alongside it carrying `data_source='ODOO'`. | Arina, 2026-09-10 |
| D4 | **Thin slice, gcloud-first.** Cloud Run + Cloud SQL + Secret Manager + two Jobs + one Scheduler job. No VPC estate. | Arina, 2026-09-10 |
| D5 | **Hybrid landing schema** — normalise the Odoo/sheet overlap into columns, keep the sheet-only blocks as JSONB in today's exact shape. | Arina, 2026-09-10 |
| D6 | **The Odoo 500-partner cap is fixed** as part of the rehost, rather than carried into the new environment. | Arina, 2026-09-10 |
| D7 | **A local, rootless PostgreSQL 16** is installed under `$HOME` for the test suite. | Arina, 2026-09-10 |
| D8 | `volt-debt-stg` **already exists and Arina holds Owner**; billing is live. | Arina, 2026-09-10 |

---

## 4. GCP topology

One project, `volt-debt-stg`, region `asia-southeast1` (A-04). The path extends
`scripts/deploy_gcp.sh`, which is already proven against this project's shape.

| Component | Configuration | Rationale |
|---|---|---|
| Cloud Run `volt-debt-uat` | One service: FastAPI serving the built frontend from `backend/static`; port 8080; `--min-instances 0` ~~`--max-instances 4`~~ `--max-instances 1` (2026-09-13: session.Store caches per process, so more than one instance serves stale tester work); `--no-allow-unauthenticated`; IAP admitting `domain:volt.co.th` | Already working. A split web tier must mint an identity token per call to a private API, which nginx cannot do natively; one origin removes that, and CORS and a second IAP session with it |
| Cloud SQL `debt-pg-stg` | PostgreSQL 16, **Enterprise edition**, `db-custom-1-3840`, zonal, 20 GB SSD, **public endpoint on with zero authorized networks and `ssl-mode=ENCRYPTED_ONLY`**, reached through Cloud Run's **native Cloud SQL connector** (`--add-cloudsql-instances`) | The load-bearing simplification. The native connector requires **no VPC, no Serverless VPC Access connector and no Cloud NAT**, deleting three §4 components at once. ~~public IP disabled~~ **superseded 2026-09-10** — the API refuses an instance with no connectivity at all, and both private-IP routes need the VPC that D4 refused; with no authorized network nothing can dial the instance over IP, so the connector plus IAM stays the only way in. Edition named explicitly because the default is now Enterprise Plus, which rejects this tier |
| Database auth | **IAM database authentication** (`cloudsql.iam_authentication=on`); `debt-api-sa` and `debt-jobs-sa` are database users | No password exists, so no password can leak. The flag is already set at `infra/terraform/cloud_sql.tf:36` |
| Secret Manager | Seven secrets — `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`, `PEAK_UAT_CONNECT_ID`, `PEAK_UAT_PASSWORD`, `PEAK_UAT_USER_TOKEN` — injected with `--set-secrets` | Names match `backend/.env.example` exactly. Names travel; values do not |
| Cloud Run Job `debt-migrate` | Applies migrations; runs to completion before a revision takes traffic | `infra/cloudbuild.yaml:33` **already executes this job by name**. Creating it resolves a dangling reference rather than inventing a component |
| Cloud Run Job `debt-odoo-sync` | Runs the Odoo pull against the landing schema | **A Job, not an HTTP call, on purpose.** Scheduler→Cloud Run behind IAP requires an OIDC token minted for the IAP client id; a Job invokes the same Python with no HTTP and no IAP in the path |
| Cloud Scheduler `odoo-reconcile` | Nightly 02:00 `Asia/Bangkok`, executing `debt-odoo-sync` | D-15 sets the 02:00 reconciliation poll. The webhook half of D-15 is out of scope |
| Cloud SQL stop/start | Two Scheduler jobs, 14h × 6 days | Drops the dominant cost line from ~USD 75 to ~35 |
| Budget alert | USD 100/month on the project | Staging-sized; v1.0 §13.2 budgets 250 for the full stack |

**Cost.** Roughly **USD 45–90/month**: Cloud SQL 35–75 depending on stop/start, Cloud Run 5–15 at
min-0, everything else under 5 combined. GCP Architecture v1.0 §13.2 prices the full staging estate
at ~219/month always-on, ~180 with stop/start.

---

## 5. The data path

### 5.1 Schema

Two schemas: `landing` for ingested source data, `app` for tester state.

```
landing.import_run      id             bigserial PK
                        source_system  text        -- 'SHEET' | 'ODOO'
                        spreadsheet_id text null
                        started_at     timestamptz
                        finished_at    timestamptz null
                        status         text        -- 'RUNNING' | 'OK' | 'FAILED'
                        row_counts     jsonb
                        reconciled     boolean null
                        truncated_blocks jsonb
                        note           text null

landing.customer        volt_id        text
                        data_source    text        -- 'SHEET' | 'ODOO'
                        customer_no, name_roman, name_th, epc, product, sales_lead,
                        phone_masked, phone_e164, email_masked   text
                        source_refs    jsonb
                        import_run_id  bigint FK
                        PRIMARY KEY (volt_id, data_source)

landing.order           volt_id        text
                        data_source    text
                        no             integer
                        crm_id, order_type, order_status, loan_status   text
                        submit_date, contract_signed_date,
                        epc_start_date, epc_end_date                    date null
                        amount_total   numeric null
                        source_ref     jsonb
                        import_run_id  bigint FK
                        PRIMARY KEY (volt_id, data_source)

landing.customer_block  volt_id        text
                        block          text   -- leasing|tracking|cash|cash_invoices|asset|contact_log
                        data_source    text
                        payload        jsonb
                        import_run_id  bigint FK
                        PRIMARY KEY (volt_id, block, data_source)

app.session_state       session_id     text
                        key            text
                        payload        jsonb
                        updated_at     timestamptz
                        PRIMARY KEY (session_id, key)
```

Three properties of this schema are load-bearing.

**`data_source` sits inside the primary key.** A SHEET row and an ODOO row for the same `volt_id`
coexist rather than overwrite. That is what makes D3's overlay expressible at all, and it turns
R5's honesty marker from a computed value into a **stored fact** — a reviewer can query which rung
served any row.

**The blocks table makes the asymmetry visible.** Odoo writes `customer` and `order` rows and
**zero** `customer_block` rows, because `sale.order` and `res.partner` contain nothing that answers
`leasing` or `tracking`. The schema states that boundary rather than hiding it behind columns full
of NULL. This is the same gap already on record as *"no partner→customer join exists."*

**The JSONB blocks keep today's exact shape.** `payload` for `block='leasing'` is byte-identical to
`fixtures_sheet.json`'s `customers[i].leasing`. That is what allows §5.2 to be a single seam.

### 5.2 The seam

Two new modules, and nothing else in the domain changes.

`backend/app/book_source.py` — `load()` returns **exactly the dict structure `book.build()`
consumes today**, so the 32 domain modules and the 158 endpoints are untouched.

When Postgres is configured it reads `landing` and resolves each row by precedence:

1. rows from the **current** successful ODOO `import_run`,
2. else rows from the **last previous** successful ODOO `import_run` (this is the SNAPSHOT rung,
   which in a deployed environment has never actually existed until now),
3. else the **SHEET** rows.

`backend/app/session.py` — `Store` keeps its `for_current()` / `reset()` / `sessions()` interface
and swaps its in-memory dict for `app.session_state`. No caller changes, because no caller reaches
past that interface.

### 5.2.1 Configured, unconfigured, and unreachable — three states, not two

This distinction is load-bearing and easy to get wrong.

| State | `book_source` | `Store` |
|---|---|---|
| **`DATABASE_URL` unset** (unit tests, CI, a laptop with no Postgres) | Reads `fixtures_sheet.json` exactly as today | In-memory, exactly as today |
| **Set and reachable** (staging) | Reads `landing` | Reads and writes `app.session_state` |
| **Set but unreachable** | **Refuses** (§6) | **Refuses** (§6) |

Without the first row, every one of the 569 backend tests would need a live database, and
`infra/cloudbuild.yaml`'s `test` step — which runs in a bare `python:3.12-slim` container with no
Postgres — would fail on the first import. The unconfigured path is therefore not a convenience;
it is what keeps the test contract and CI intact.

The refusal rule in §6 applies **only to the third row**. A configured database that has gone away
must never degrade to fixtures or to memory, because that failure would look exactly like success.

This is why the test contract is expected to hold without a single edit: the change stops at two
boundaries the code already respects, and the default path through both is unchanged.

### 5.3 Ingestion

Three entry points, each opening exactly one `import_run`:

1. `scripts/import_master_sheet.py --to-postgres` — the sheet path. Existing parse logic unchanged;
   a writer is added. Reconciliation against the sheet's own pivots and the `truncated_blocks`
   report are carried into `import_run` rather than discarded.
2. `backend/app/integrations/odoo.py:sync()` — writes to `landing` instead of
   `backend/var/odoo_snapshot.json`. `cached_snapshot()` reads the last successful ODOO
   `import_run` from Postgres, which is what finally makes the middle rung of the fallback chain
   real in a deployed environment.
3. `POST /v1/integrations/odoo:sync` — externally unchanged, Manager-only, same response shape.
   The Cloud Run Job calls the same function.

**Atomicity.** One import run is one transaction. A failed run leaves the **previous** run's rows
serving; there is no state in which half a book is visible.

### 5.4 The Odoo pagination fix (D6)

`odoo.py:sync()` currently fetches partners with `{"limit": 500}` against an instance whose own code
comment records ~127,963 partners, and *"missed every one of the five live orders on 2026-09-09,
which is how they all rendered '(no name)'."* The fix pages `res.partner` with `offset`/`limit`
until exhausted, or — better and cheaper — fetches only the partner ids actually referenced by the
orders in hand. The second is preferred: it is bounded by the order count, not the partner count.

A regression test pins the behaviour: given more partners than one page, every order resolves a
name.

---

## 6. Error handling

`backend/app/config.py` already draws the operative line — `RUNNING` and `REFUSING` are both
honest, `LEAKING` is not. That principle governs every failure below.

| Failure | Behaviour |
|---|---|
| Migration fails | `debt-migrate` exits non-zero; the new revision never takes traffic. This is why `cloudbuild.yaml` sequences `migrate` before `deploy-api` |
| Odoo unreachable or refuses login | The run is recorded `FAILED`; serving degrades down `ODOO → last good landing rows → SHEET`. No partial overwrite |
| Import run fails midway | Transaction rolls back; the previous run keeps serving; `import_run.status='FAILED'` with the reason |
| Cloud SQL **configured but** unreachable | The API **refuses**. It does **not** fall back to fixtures or to in-memory state — that would silently resurrect the defect this work exists to remove, while looking like success. Contrast §5.2.1: a database that was never configured is a different state and behaves as today |
| Session state write fails | The write is refused and surfaced to the officer, never dropped silently |

---

## 7. Gap list against GCP Architecture v1.0

Not built, and each named so promotion to `prd` is an addition set rather than a rewrite.

| §  | Component | Why not now | To add |
|---|---|---|---|
| 4.1–4.3 | VPC, Serverless VPC connector, Cloud NAT | The native Cloud SQL connector removes the need | Required before any private-IP service other than Cloud SQL, and before fixed NAT egress IPs for the Odoo droplet firewall (§15.2) |
| 4.4–4.5 | Load Balancer, Cloud Armor | IAP on the Cloud Run service is sufficient for a closed UAT round | Required for a public origin, WAF rules, or a custom domain with managed certs |
| 6.5 | Memorystore Redis | Nothing in the prototype rate-limits or caches | Add when rate limiting lands |
| 7.1–7.2 | Pub/Sub, Cloud Tasks | No outbox exists in the prototype | Required for A-05's n8n gateway and the transactional outbox |
| 9.1 | Identity Platform | IAP + Google sign-in restricted to `volt.co.th` covers a UAT round | Required for D-08 proper: per-user identity, the blocking function, `iam_user` provisioning |
| 9.4 | Cloud KMS / CMEK | Google-managed encryption for a staging host | Required by §14 for production |
| 6.2 | The twelve Data_Model schemas | Out of scope by D1 | The MVP build |

---

## 8. Testing

**The contract.** Baseline **569 backend / 443 frontend (33 files) / 29 e2e**;
`./scripts/verify_all.sh` is the authority. Run `pytest` **without** `-q` — `backend/pytest.ini:4`
already sets it and doubling it collapses the summary into bare dots.

**The rule.** Adding tests is free. **A test that must change is escalated to Arina, never edited.**
The seam design in §5.2 is chosen precisely so that no existing test should need to move; if a
stream finds it cannot proceed without an edit, that stream **stops and asks** rather than spending
from the authorised-edit ledger. Edit 17 remains reserved for ruling 74 and is not a spare.

**One CI defect found while writing this.** `infra/cloudbuild.yaml:12` runs `pytest -q` while
`backend/pytest.ini:4` already sets `-q`. The doubled flag collapses the summary into bare dots,
which reads exactly like a failure — the same trap the README warns about for local runs. Worth
correcting in the same pass.

**The harness.** PostgreSQL 16 installed rootless under `$HOME` (D7), the same pattern already used
for the Python 3.12 that gcloud requires (`~/.volt-gcloud-env`), running on a high port with its
data directory under `backend/var/`. Real Postgres means real JSONB, real transactions and real
constraint behaviour — bugs surface locally instead of in staging.

**Test-first, per unit:** schema round-trip; loader precedence across the three rungs; session state
surviving a simulated restart; Odoo pagination resolving every order's name; import-run atomicity
under a mid-run failure; the refusal path when the database is unreachable.

---

## 9. Delivery

Six streams in three waves, dispatched in parallel where dependencies allow.

**Wave 1** — *(two of these start immediately)*
1. Schema + migrations + the `debt-migrate` job entrypoint *(blocks wave 2)*
2. GCP provisioning scripts for the §4 topology
3. The guidebook

**Wave 2** — all parallel once stream 1 lands
4. `book_source.load()` and the `Store` swap
5. `import_master_sheet.py --to-postgres`
6. Odoo rehost + the D6 pagination fix

**Wave 3** — integration, deploy, verification.

**Skill activation**, as requested: `brainstorming` (this document) → `writing-plans` /
`executing-plans` (the phased plan) → `dispatching-parallel-agents` (waves 1–3) →
`test-driven-development` (inside every stream, per unit) → `verification-before-completion`
(per stream before it reports done, and as the wave 3 gate).

---

## 10. Manual versus automated

The split turns on one fact: **once Arina runs `gcloud auth login`, subsequent `gcloud` commands run
as her.** Verified state on this machine: gcloud SDK 582.0.0 is installed at `~/google-cloud-sdk`
with **no credentialed accounts**; `terraform` and `docker` are **not installed**.

**Arina, unavoidably:**
1. `gcloud auth login` — browser-interactive.
2. Confirm the project id and that billing is live.
3. The **IAP OAuth consent screen** — console-only, no API covers it.
4. Push the seven secret values. The command reads `backend/.env` directly so no value is echoed
   into a transcript, which still satisfies §15.1 step 3's *"from a laptop, never via CI."*

**Automated, after authentication:** API enablement, the Cloud SQL instance and database, IAM
database users, service accounts and bindings, both Cloud Run Jobs, the Scheduler jobs, the budget,
schema DDL, all application code, all tests, and the deploy.

**The guidebook** is written to `/Users/parattakorn/Documents/Obsidian Vault/Debt modules (self
build)/`: an index; a *you do this* page with exact commands and what each is for; an *I do this*
page so the work is auditable; the §7 gap list; and a rollback/teardown page — a staging
environment that cannot be deleted is a cost leak.

---

## 11. Acceptance criteria

1. `./scripts/verify_all.sh` is green at or above 569 / 443 / 29, counts pasted, **with no test
   edited**.
2. With `DATABASE_URL` unset, the suite behaves exactly as it does today — proving the
   unconfigured path of §5.2.1 and keeping CI green.
3. A fresh `debt-migrate` run against an empty database creates both schemas cleanly.
4. The sheet import loads 418 customers into `landing`, and `import_run` reconciles against the
   sheet's own pivots.
5. An Odoo sync writes `landing.customer` and `landing.order` rows carrying `data_source='ODOO'`,
   and **every order resolves a name** (the D6 fix).
6. **A Cloud Run revision restart does not lose a tester's work** — the criterion this whole design
   exists to satisfy.
7. Cloud SQL made unreachable produces a refusal, not silent in-memory service.
8. The guidebook exists in the vault, and its manual steps have been executed by Arina at least
   once from the text as written.

---

## 12. Risks and open items

- **IAP and the OAuth consent screen** are console-only. If the project has no consent screen
  configured, step 3 of §10 blocks the deploy and cannot be worked around from the CLI.
- **`terraform` is not installed.** The thin slice is provisioned with `gcloud`; if Terraform parity
  is wanted later, installing it is a prerequisite, not a detail.
- **PDPA.** The sheet carries real customer names with masked phone and email. This is the same
  data the existing UAT deploy already ships, so no new exposure is created — but `asia-southeast1`
  is Singapore, and A-04 handles cross-border by contract and DPA. Flagged, not resolved here.
- **`Debt working sheet + sample docs`** (folder `1QmYKFvIv8iI1LFFWzVP-S_6hxbmZLTEr`) still cannot
  be enumerated from this account, exactly as on 2026-09-08. D2 makes it irrelevant to this design,
  but it remains unread.
- **The webhook half of D-15** is not built. Staging reconciles nightly only, so Odoo changes are up
  to 24 hours stale.
