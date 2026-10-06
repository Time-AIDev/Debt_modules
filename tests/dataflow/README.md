# Dataflow regression

This index covers intake, persistence, domain calculations, publication and client transport. Existing units are reused; new boundary tests exercise provider errors, repeated pages, redelivery, lock release, typed persistence and out-of-order client responses.

## Run

From the repository root, with Python 3.12 and Docker available:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-test.txt
backend/.venv/bin/python scripts/test_dataflow.py --unit
backend/.venv/bin/python scripts/test_dataflow.py --all --coverage
```

`--unit` runs units and in-memory API contracts; tests needing `pg_url` or `pg_conn` are deselected. `--all` provisions a fresh PostgreSQL database bound only to loopback, runs SQL integration/atomicity tests, and removes it afterward. The script never accepts a production database URL. Connector credentials and the developer dotenv are excluded; external provider DNS is blocked and providers are mocked. Frontend tests use local npm or a Docker build of the canonical Node environment, with network disabled during tests.

Use `--backend-only`, `--frontend-only` or `--backend-tests tests/test_pipeline_ingress.py` for a focused run. `--postgres-image` selects the test PostgreSQL image. A forced process kill can leave a labelled test container; inspect the `volt.test.dataflow` label and remove only that test container before restarting.

## Evidence

The default private, gitignored destination is `.test-artifacts/dataflow/`: backend/frontend JUnit, logs, `summary.json`, and optional backend line/branch JSON plus HTML. A flow can reference the same test as another flow, so flow counts must not be summed as unique tests. Skipped/deselected tests are not passes. A mapped flow is not a claim of 100% branch coverage. Browser Google login, real-provider availability, k6 capacity, and disaster recovery are separate checks.

## Indexed flows

| Flow | Backend files | Frontend files |
|---|---:|---:|
| Odoo authentication, keyset pull, rules, identity and landing | 9 | 1 |
| Master/manual file parsing, review, install and source priority | 9 | 1 |
| PEAK invoice report, matching, staging, conflicts and apply | 9 | 2 |
| Receipts, cash, cancellations and reconciliation | 7 | 1 |
| Schedules, DPD, allocations, arrears, fees, balances and deferrals | 11 | 3 |
| Orders, pre-installation, evidence and approval/release gates | 5 | 2 |
| Assignments, roles, locks and scoped customer access | 8 | 2 |
| Contact/disposition, promises, Today, reviews and worked status | 8 | 3 |
| NPL, recovery, termination and immutable archive | 6 | 3 |
| Appointments, reschedules, messages and notices | 6 | 2 |
| Chunk assembly, ownership, scanner, integrity, quotas and retention | 7 | 1 |
| Outbox, delivery, retry, acknowledgement and dead letter | 7 | 1 |
| Durable/legacy scheduling, cancellation and background job payload | 5 | 0 |
| Typed records, transaction rollback, idempotency and concurrent snapshots | 6 | 0 |
| Import epoch, book refresh, session healing and client dataflow | 6 | 4 |
| Reports, monthly snapshots, totals, filters and CSV/export safety | 9 | 3 |
| Audit provenance, actor identity, hash chain and refusal coverage | 7 | 1 |
| Authentication, revocation, per-tab state, version conflicts and uncertain retries | 7 | 5 |
| Runtime parity, migrations, readiness, storage and release safeguards | 8 | 0 |

## CRM eligibility

Shared dev/staging/production profiles default to `CRM_WON_ONLY=true`: active Won leads are eligible even without install dates. Strict legacy mode (`false`) additionally requires both EPC install dates. The Odoo page size of 500 is a batch size, not a total import limit. Normalisation can refuse duplicate Volt IDs; raw lead count and unique landed customer count must be reported separately. Tests cover both policies and the provider pagination contract.
