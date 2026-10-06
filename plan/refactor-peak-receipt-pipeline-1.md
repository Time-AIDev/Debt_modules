---
goal: Stabilize and accelerate the PEAK receipt parsing, matching, landing, and upload-feedback pipeline
version: 1.0
date_created: 2026-10-01
last_updated: 2026-10-01
owner: Volt Debt engineering
status: 'Implemented locally — UAT pending'
tags: [bugfix, performance, parsing, peak, receipts, observability, frontend]
---

# Introduction

![Status: Implemented locally — UAT pending](https://img.shields.io/badge/status-Implemented_locally_%E2%80%94_UAT_pending-orange)

This plan fixes the deterministic receipt-matching crash, normalizes the receipt candidate contract, makes every long-running stage visible to the upload screen, reduces measured XLSX and header-discovery cost, and adds privacy-safe operational diagnostics. The plan is based on a measured 1.9 MB PEAK receipt workbook that inflated to 20.2 MB of XLSX XML, parsed 5,889 lines into 5,399 receipts with zero rejected rows, and took 3.36 seconds locally. The observed failure is not a schema parse failure: `receipt_match_verdict()` can raise `TypeError: unhashable type: 'dict'` after parsing when it mixes string and object candidates before calling `dict.fromkeys()`.

## Implementation verification (2026-10-01)

- Implemented the canonical candidate contract, legacy read compatibility, reviewable candidate tab, honest phase progress, bounded header scan, shared XLSX hot-path optimization, safe failure location, stage timing logs, and privacy-safe benchmark utility.
- Parsed every non-lock workbook in `/Users/parattakorn/Documents/Debt`: invoices `7,638 / 7,998 / 0 rejected` and `9,343 / 11,744 / 0 rejected`; receipts `5,399 / 5,889 / 0 rejected` and `320 / 346 / 0 rejected`. The lock file returns `unreadable`.
- Full-year receipt benchmark reached a final isolated median of `2.112s`, down from `3.36s` (about 37.1%). Runs while the full suite saturated the machine were intentionally not used as acceptance evidence.
- A local end-to-end full-year run on a dedicated scratch PostgreSQL database completed and applied successfully in `5.913s`: reading `3,984ms`, matching `1,452ms`, writing `459ms`, `5,399` receipts, `0` rejected. The scratch database was dropped immediately after verification.
- Focused backend receipt/import suites, all 325 frontend tests, the frontend production build, Python compileall, and `git diff --check` pass. The repository-wide Python run has 2,092 passing and 14 skipped tests plus 18 pre-existing stale guide-citation failures for files/line numbers outside this change.
- Still pending external authority/state: historical Cloud Run log lookup (expired `gcloud` authentication), browser-based UAT on the deployed environment, and deployment.

## 1. Requirements & Constraints

- **REQ-001**: A receipt whose referenced invoice exists and whose independent identity verdict is `CANDIDATE` must finish as a reviewable `CANDIDATE` row and must never terminate the import run.
- **REQ-002**: Every receipt candidate returned by new backend code must use the canonical object shape `{ "customer_no": string, "rule": string | null, "code": string | null }`; candidate order must be deterministic and candidates must be deduplicated by `customer_no`, preserving first appearance.
- **REQ-003**: Existing landed receipt rows whose `candidates` JSON contains legacy strings must remain readable and reviewable without a database rewrite.
- **REQ-004**: Receipt upload run views must expose a stable `phase` value from the enum `queued`, `reading`, `matching`, `writing`, `done`, `failed`; matching progress must expose `processed` and `phase_total`, while existing `read`, `total`, and `landed` fields remain backward compatible.
- **REQ-005**: The frontend must display an indeterminate progress state during `queued` and `reading`, a determinate state during `matching` and `writing`, and must continue polling every two seconds until `done` or `failed`.
- **REQ-006**: The parser must continue accepting the proven PEAK receipt schemas, contextual duplicate `จำนวนเงิน` binding, reordered optional fields, BOM/NBSP/newline headers, and `PAID`, `DRAFT`, and `CANCELLED` statuses.
- **REQ-007**: The full-year reference workbook must parse to 5,399 receipts from 5,889 kept lines with zero rejected rows; the September reference workbook must parse to 320 receipts from 346 kept lines with zero rejected rows.
- **REQ-008**: Header discovery must inspect at most the first 100 materialized worksheet rows and must still choose the highest-scoring PEAK header within that window; if no valid header is present, it must return `header_not_found`.
- **REQ-009**: Performance work must be driven by before/after profiling. On the same reference machine, median pure-parser time for the full-year receipt workbook must be no slower than 3.36 seconds and must target at least a 15% reduction. A missed target blocks the performance commit but does not block the correctness fix.
- **REQ-010**: An end-to-end UAT receipt run for the full-year workbook must reach `done` within 20 seconds under normal single-run load; if infrastructure variance prevents this target, record stage timings and identify the exceeding stage rather than weakening correctness.
- **REQ-011**: Unexpected failures must emit a structured, privacy-safe server log containing run UID, phase, exception class, and the final application frame as `module:function:line`; logs and client responses must not contain raw spreadsheet cell values, names, tax IDs, notes, SQL parameters, or exception messages.
- **REQ-012**: Known `ReportError` and `PipelineRefused` responses must preserve their existing public error codes and schema diagnostics; unexpected failures must remain publicly represented by `pipeline_failed`.
- **REQ-013**: No real PEAK workbook from `/Users/parattakorn/Documents/Debt` may be committed. Repository fixtures must be generated and sanitized.
- **REQ-014**: No database migration is required. Compatibility for legacy candidate JSON must be implemented at read time.
- **SEC-001**: The 13-digit tax ID must remain parse-time-only and must never be written to landing tables, logs, run problems, or test snapshots.
- **SEC-002**: Failure diagnostics must be derived from exception type and traceback frame metadata only; `str(exception)` and row contents must not be logged for unexpected failures.
- **CON-001**: Keep `app.imports.read_xlsx()` as the single XLSX implementation shared by invoice and receipt imports; do not introduce openpyxl, pandas, or a second workbook parser.
- **CON-002**: Preserve `POST /v1/pipelines/peak-receipt:start`, `GET /v1/pipelines/peak-receipt/runs/{uid}`, and the current asynchronous background-run behavior.
- **CON-003**: Preserve current invoice matching safety: an invoice reference alone must not confirm payment when the independently matched customer differs or is ambiguous.
- **GUD-001**: Implement correctness changes with failing regression tests first, then add the minimum code required to pass them.
- **GUD-002**: Treat parser, matching, database landing, and UI progress as separately measurable phases; do not report fabricated row percentages while XLSX parsing has no row-count callback.
- **PAT-001**: Normalize data at backend boundaries and keep the frontend tolerant of legacy data; do not duplicate matching or export logic in React.

## 2. Implementation Steps

### Implementation Phase 1: Lock the failure reproduction and candidate contract

- GOAL-001: Convert the confirmed mixed-candidate `TypeError` and the legacy candidate shape into deterministic regression tests before changing production code.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Add a unit test in `backend/tests/test_peak_receipt.py` that calls `receipt_match_verdict()` with a found invoice and an identity verdict containing object candidates; assert that the current code raises `TypeError` before implementation, then retain the test with the final expected canonical candidate list. | | |
| TASK-002 | Add unit cases for: found invoice plus mismatched `EXACT` identity; found invoice plus `CANDIDATE` identity; found invoice plus `UNMATCHED` identity; missing invoice plus `EXACT` identity; missing invoice plus `CANDIDATE` identity; duplicate customer numbers arriving through invoice and identity paths. | | |
| TASK-003 | Add a DB-backed route test in `backend/tests/test_peak_receipt_router.py` that lands an applied invoice, supplies a receipt with an ambiguous identity proposal, executes `run_receipt_upload()`, and asserts `state == "done"`, `verdict == "CANDIDATE"`, and canonical object candidates in the rows endpoint. | | |
| TASK-004 | Add frontend tests in `frontend/src/components/ReceiptIntake.test.jsx` for canonical object candidates and legacy string candidates; assert both render a usable customer number without `undefined` and can open the link drawer. | | |

### Implementation Phase 2: Fix receipt matching without weakening allocation safety

- GOAL-002: Make candidate construction type-safe and canonical while preserving the two-factor invoice-reference-and-customer confirmation rule.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-005 | Add private helpers in `backend/app/pipelines/peak_service.py`: `_candidate(customer_no, rule=None, code=None)` to build one canonical object and `_merge_candidates(*groups)` to accept strings or objects, discard empty customer numbers, coerce `customer_no` to string, preserve `rule` and `code` when present, and deduplicate by `customer_no` in first-seen order. | | |
| TASK-006 | Replace the mixed list and `dict.fromkeys()` logic in `receipt_match_verdict()` with `_merge_candidates()`. Insert the invoice customer first with rule `INVOICE_REF_CUSTOMER` and code equal to the receipt invoice reference, followed by the independently matched identity customer or identity candidates. | | |
| TASK-007 | Change the missing-invoice plus `EXACT` branch to return a canonical candidate object instead of a string. Do not change the verdict, rule, `customer_no`, or `invoice_doc_no` semantics of any branch. | | |
| TASK-008 | Add a read-time normalizer in `backend/app/pipelines/peak_writer.py` for `receipt_rows()` so legacy candidate strings are served as canonical objects with `rule: null` and `code: null`; leave stored historical JSON untouched. | | |
| TASK-009 | Run the focused backend receipt parser, service, writer, and router tests. Confirm that no test permits an invoice reference to become `EXACT` without the same independently matched customer. | | |

### Implementation Phase 3: Add honest stage progress and frontend feedback

- GOAL-003: Make the upload visibly active from queueing through XLSX read, matching, and database landing without inventing parser percentages.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-010 | Extend the initial run record in `backend/app/pipelines/runs.py` with `phase: "queued"`, `processed: 0`, and `phase_total: null`; retain all existing fields and make `finish()` set `phase: "done"` while `fail()` sets `phase: "failed"`. | | |
| TASK-011 | In `run_receipt_upload()` set `phase: "reading"` before `peak_receipt.parse()`, then set `phase: "matching"`, `processed: 0`, and `phase_total` to the receipt count before `_land()`. Set `phase: "writing"` before row COPY begins. | | |
| TASK-012 | Add an optional `on_progress(processed, total)` callback to `_receipt_verdicts()` and invoke it every 500 receipts and once at completion. Thread this callback through `_land()` to `runs.progress()` without changing invoice-run behavior. | | |
| TASK-013 | Preserve the existing `_write_receipt_rows()` 500-row `landed` callbacks and update the run phase to `writing` before the first callback. Ensure monotonic values: `0 <= processed <= phase_total` and `0 <= landed <= total`. | | |
| TASK-014 | Update `frontend/src/components/ReceiptIntake.jsx` and `frontend/src/components/import/parts.jsx` to display localized phase-specific text. Render an indeterminate bar for `queued` and `reading`; render matching as `processed / phase_total`; render writing as `landed / total`. | | |
| TASK-015 | Add Thai and English keys for queued, reading, matching, writing, and the new candidate rule `INVOICE_REF_CUSTOMER` in `frontend/src/lib/i18n/th.js` and `frontend/src/lib/i18n/en.js`. Keep `role="status"` and ensure phase changes are announced without moving focus. | | |
| TASK-016 | Add backend run-state tests and frontend polling/rendering tests for every phase, terminal failure, terminal success, missing totals, and page restoration from `last-run`. | | |

### Implementation Phase 4: Remove measured parser waste

- GOAL-004: Reduce CPU time in the two measured hotspots while preserving the shared XLSX parser contract.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-017 | Add a benchmark utility under `scripts/bench_peak_receipt.py` that accepts a workbook path, performs one warm-up plus five measured parses, and reports median and maximum time, receipt count, kept line count, rejected count, and process peak RSS without printing row values. | | |
| TASK-018 | Change `_find_header()` in `backend/app/pipelines/peak_report.py` to scan `table[:100]`, preserving highest-score and earliest-row tie-breaking. Add tests with the header on rows 1, 11, 100, and 101; row 100 must pass and row 101 must return `header_not_found`. | | |
| TASK-019 | Profile `app.imports._sheet_rows()`, `_row_cells()`, `_local()`, and `_col_index()` again after TASK-018. Implement only optimizations that preserve all import tests, prioritizing removal of repeated regex work in `_col_index()` and repeated namespace-string allocation in hot tag checks. | | |
| TASK-020 | Run the benchmark before and after TASK-019 against both real receipt workbooks outside the repository. Record results in the commit message or UAT evidence, not in a committed file containing customer filenames if those names are considered sensitive. | | |
| TASK-021 | Reject any parser optimization that changes parsed receipt values, schema diagnostics, row numbering, date handling, money handling, lock-file refusal, or memory safety of the streamed XML reader. | | |

### Implementation Phase 5: Add privacy-safe failure location and stage timing

- GOAL-005: Make future failures diagnosable from Cloud Run logs without exposing spreadsheet or customer data.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-022 | Add a private traceback-location helper in `backend/app/pipelines/peak_service.py` that selects the last traceback frame under `backend/app/` and returns only repository-relative module path, function name, and line number. | | |
| TASK-023 | Track monotonic timestamps for reading, matching, and writing inside `run_receipt_upload()` and emit one structured completion log containing run UID, receipt count, and per-stage milliseconds. Do not log filename, spreadsheet values, or customer identifiers. | | |
| TASK-024 | Replace the current unexpected-failure log with a structured safe log containing run UID, current phase, exception class, and sanitized failure location. Do not use `log.exception()`, traceback text, or `str(exc)`. | | |
| TASK-025 | Keep the public problem code `pipeline_failed` and existing Thai generic message. Add tests using an exception whose message contains a fake tax ID and customer name; assert neither value appears in captured logs, run problems, or durable failure notes. | | |
| TASK-026 | After refreshing local `gcloud` authentication, query the historical UAT run around 2026-09-30 22:57 Asia/Bangkok and record only the exception class and failure location in the implementation verification notes. Do not block TASK-005 through TASK-025 if the historical log is unavailable. | | |

### Implementation Phase 6: Full regression, real-file verification, and UAT release

- GOAL-006: Prove correctness, performance, privacy, and deployment behavior before releasing the fix.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-027 | Generate and commit sanitized receipt fixtures that reproduce: found invoice plus object candidate; duplicate candidate customer numbers; contextual duplicate `จำนวนเงิน`; optional and extra columns; BOM/NBSP/newline headings; invalid date; invalid money; unknown status; and wrong report type. | | |
| TASK-028 | Run every non-lock receipt workbook in `/Users/parattakorn/Documents/Debt` through `peak_receipt.parse()` and assert expected counts and zero rejected rows. Assert the `~$` lock file returns `unreadable`. Never copy these files into the repository or test output. | | |
| TASK-029 | Run focused backend tests, the complete backend suite, the complete frontend suite, frontend production build, `python -m compileall backend/app`, and `git diff --check`. | | |
| TASK-030 | Perform an authenticated local or ephemeral-Postgres end-to-end run of the full-year receipt workbook through start, polling, matching, landing, row review, and apply. Verify monotonic phases and that no payment is confirmed for ambiguous identity matches. | | |
| TASK-031 | Deploy backend and frontend together because the new run fields are additive and the frontend remains compatible with absent phase fields. Verify `/livez`, `/readyz`, login, schemas, invoice upload, and receipt upload smoke tests. | | |
| TASK-032 | In UAT, upload the full-year receipt workbook, capture total duration and per-stage timings, verify the run reaches `done`, inspect at least one ambiguous candidate and one exact match, then apply only if counts and customer ownership are correct. | | |
| TASK-033 | Confirm Cloud Run logs contain safe stage/timing fields and contain no names, tax IDs, spreadsheet notes, raw SQL parameter values, or exception messages. | | |
| TASK-034 | Commit the verified changes, push the branch, and document the deployed revision, migration status `not required`, test totals, reference-file counts, and UAT timing in the final implementation report. | | |

## 3. Alternatives

- **ALT-001**: Convert every candidate to a plain customer-number string. Rejected because the review UI and matching diagnostics require `rule` and `code` metadata.
- **ALT-002**: Hash serialized candidate dictionaries before `dict.fromkeys()`. Rejected because it preserves an inconsistent public shape and makes deduplication depend on dictionary serialization details.
- **ALT-003**: Add openpyxl or pandas for faster or simpler workbook reading. Rejected because it creates a second parser, increases image size and memory risk, and violates the existing shared-reader constraint.
- **ALT-004**: Emit a per-row XLSX percentage during parsing. Deferred because the current shared reader materializes rows before the receipt parser knows a trustworthy total; phase-level indeterminate feedback is honest and lower risk.
- **ALT-005**: Rewrite all legacy `candidates` JSON with a database migration. Rejected because read-time normalization is sufficient, reversible, and avoids modifying historical landing evidence.
- **ALT-006**: Return full exception tracebacks to the browser or Cloud logs. Rejected because exception values and database errors can expose customer data.

## 4. Dependencies

- **DEP-001**: Existing Python standard-library XLSX reader in `backend/app/imports.py`.
- **DEP-002**: Existing PEAK invoice and receipt schema helpers in `backend/app/pipelines/peak_report.py` and `backend/app/pipelines/peak_receipt.py`.
- **DEP-003**: Existing PostgreSQL test fixture used by `backend/tests/test_peak_receipt_router.py` for landing and rows-endpoint coverage.
- **DEP-004**: Existing in-memory pipeline run registry in `backend/app/pipelines/runs.py`.
- **DEP-005**: Real PEAK workbooks kept outside Git under `/Users/parattakorn/Documents/Debt` for local acceptance testing only.
- **DEP-006**: Refreshed Google Cloud authentication for historical log inspection and UAT deployment verification; implementation correctness does not depend on this credential.

## 5. Files

- **FILE-001**: `backend/app/pipelines/peak_service.py` — candidate normalization, matching progress, phase tracking, safe failure location, and stage timing.
- **FILE-002**: `backend/app/pipelines/peak_writer.py` — legacy receipt-candidate read normalization and writing-phase callback behavior.
- **FILE-003**: `backend/app/pipelines/peak_report.py` — bounded PEAK header discovery.
- **FILE-004**: `backend/app/imports.py` — profile-gated XLSX hot-path optimization.
- **FILE-005**: `backend/app/pipelines/runs.py` — additive run phase and phase-progress fields.
- **FILE-006**: `backend/tests/test_peak_receipt.py` — pure matching and parser regressions.
- **FILE-007**: `backend/tests/test_peak_receipt_router.py` — DB-backed full-run and rows-contract regressions.
- **FILE-008**: `backend/tests/test_peak_report.py` — bounded header-search tests shared by invoice and receipt parsers.
- **FILE-009**: `backend/tests/test_imports.py` — shared XLSX reader correctness and optimization regressions.
- **FILE-010**: `frontend/src/components/ReceiptIntake.jsx` — phase-aware receipt upload feedback.
- **FILE-011**: `frontend/src/components/import/parts.jsx` — indeterminate progress and legacy candidate tolerance.
- **FILE-012**: `frontend/src/components/ReceiptIntake.test.jsx` — phase, polling, and candidate rendering tests.
- **FILE-013**: `frontend/src/lib/i18n/th.js` — Thai progress-phase messages.
- **FILE-014**: `frontend/src/lib/i18n/en.js` — English progress-phase messages.
- **FILE-015**: `scripts/bench_peak_receipt.py` — privacy-safe repeatable parser benchmark.
- **FILE-016**: `backend/tests/fixtures/peak/` — generated sanitized XLSX/CSV receipt fixtures; no real customer workbook.

## 6. Testing

- **TEST-001**: Pure unit test proves object candidates no longer raise `TypeError` and are deduplicated by customer number.
- **TEST-002**: Pure unit matrix proves only matching invoice ownership plus independently exact identity can produce `EXACT`.
- **TEST-003**: DB-backed run proves ambiguous receipt identity lands as `CANDIDATE` and the run reaches `done`.
- **TEST-004**: Rows endpoint proves both newly written object candidates and legacy string candidates are returned canonically.
- **TEST-005**: Frontend component tests prove legacy and canonical candidates render and remain linkable.
- **TEST-006**: Run-state tests prove phase transitions are `queued -> reading -> matching -> writing -> done` or terminate at `failed`, with monotonic counters.
- **TEST-007**: Frontend tests prove indeterminate and determinate progress states, two-second polling, terminal stop, and accessible status announcements.
- **TEST-008**: Header tests prove the first-100-row boundary and preserve strongest-score and earliest-row tie-breaking.
- **TEST-009**: XLSX reader regression tests prove dates, money strings, sparse rows, shared strings, inline strings, formulas without cached values, and streamed memory behavior are unchanged.
- **TEST-010**: Sanitized schema fixtures prove duplicate headings, optional/extra columns, reordered fields, normalized headings, statuses, invalid cells, and wrong-report refusal.
- **TEST-011**: Real-file local acceptance proves 5,399/5,889 and 320/346 receipt/line counts with zero rejected rows and lock-file refusal.
- **TEST-012**: Benchmark proves no parser regression and records whether the 15% target is reached.
- **TEST-013**: Privacy test proves fake PII in exception messages never enters logs, run responses, or durable notes.
- **TEST-014**: Full backend and frontend suites, production build, compileall, and diff check pass.
- **TEST-015**: UAT smoke test proves the full-year run reaches `done` within the target or yields stage timing that isolates any infrastructure bottleneck.

## 7. Risks & Assumptions

- **RISK-001**: The screenshot workbook named with export timestamp `225738` is not present locally; the measured full-year workbook has equivalent coverage and schema but a different timestamp, so the historical Cloud log is needed to prove the exact failing frame for that run.
- **RISK-002**: Bounding header discovery to 100 rows intentionally refuses nonstandard workbooks with a header below row 100; this is acceptable for verified PEAK exports and prevents a full-table header scan.
- **RISK-003**: Shared XLSX hot-path changes can affect non-PEAK imports. TASK-019 must not merge unless the complete imports and backend suites pass.
- **RISK-004**: Cloud Run cold starts and Cloud SQL contention may exceed the UAT duration target independently of parser CPU. Stage timings must distinguish application cost from infrastructure latency.
- **RISK-005**: Historical candidate arrays may contain mixed or malformed JSON values beyond strings and objects. The read normalizer must discard invalid entries safely without making them actionable matches.
- **ASSUMPTION-001**: The deployed code contains the same mixed-candidate implementation currently at `backend/app/pipelines/peak_service.py:146-150`.
- **ASSUMPTION-002**: PEAK receipt headers remain within the first 100 worksheet rows; verified files place the header on row 11.
- **ASSUMPTION-003**: The reference workbook with 5,399 receipts is representative of the largest routine receipt upload.
- **ASSUMPTION-004**: Existing API consumers ignore additive run fields and remain compatible with `phase`, `processed`, and `phase_total`.
- **ASSUMPTION-005**: No schema migration is needed because `landing.peak_receipt.candidates` is already JSONB and can store the canonical objects.

## 8. Related Specifications / Further Reading

- [PEAK receipt parser](../backend/app/pipelines/peak_receipt.py)
- [PEAK receipt pipeline service](../backend/app/pipelines/peak_service.py)
- [PEAK landing writer](../backend/app/pipelines/peak_writer.py)
- [Shared XLSX reader](../backend/app/imports.py)
- [Receipt intake UI](../frontend/src/components/ReceiptIntake.jsx)
- [Receipt pipeline tests](../backend/tests/test_peak_receipt_router.py)
