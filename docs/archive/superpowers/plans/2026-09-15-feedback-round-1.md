# Feedback Round 1 — Implementation Plan (Round A at step level; Rounds B and C tasked)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status: DRAFT — awaiting Arina's rulings on [[10 - Feedback Round 1 - Design]] §4 (F1–F19). Nothing here is started.** Written 2026-09-15 against branch `design-team` at `f8acc2e`. When approved, this note is copied verbatim to `docs/archive/superpowers/plans/2026-09-15-feedback-round-1.md` and committed; the vault copy stays the review copy.

**Goal:** Make the PEAK invoice report the Debt team's source of monthly payment truth (matched to customers by readable rules, never guessed), import only new Odoo customers, put the contract scorecard and paid/unpaid counts on the case and in the Save-contact dialog, and let a contact carry several notes with checked attachments and its full history.

**Architecture:** Round A adds two new doors and one new mode to the pipeline machinery that already exists (`pipelines/*`, the intake desk on Data sources), one new landing table for PEAK invoices, one new durable schema `records` for things that must outlive a deploy (identity links, attachments), and one server-owned block (`payment_position`) served beside `money_position`. The domain reads PEAK facts through the same seam it reads the sheet (`book_source` → `customer.sheet["peak"]`), so no screen learns a second data path. Every figure is produced once on the server; the browser formats and never adds.

**Tech Stack:** FastAPI + SQLAlchemy core on PostgreSQL (existing), Python standard library only for parsing, guarding and hashing (no new packages); React 18 + Vite + vitest (existing). No `python-multipart`, no OCR, no new npm packages.

**Spec:** [[10 - Feedback Round 1 - Design]] (vault, this folder). Sections cited as "design §3 WP1", "design F3".

## Global Constraints

- **Authority ladder:** Requirements Amendment v2.6 §1 (`briefs/realignment/requirements_amendment_v2_6.html`). Deck v20.0 is not a ranked row. Where WP1 lets PEAK facts drive `payment_status_system` (design F2) it partly supersedes v2.6 §3.6 a second time; that is recorded at the code site and in the commit message, as the 2026-09-14 spec did.
- **Test contract:** green at or above the baseline measured in Task 0, counts pasted in every task's "run the suite" step. **A pinned test that must change is escalated to Arina, never edited.** Adding tests is free and is how every task here is paid for. The edit numbers this plan may spend are **35–39** (design F17); 17 stays reserved.
- **Density ratchets:** `frontend/src/density.test.jsx` caps CustomerCase at **104 pre-contact / 123 worked**; `frontend/src/today-density.test.jsx` caps Today at **31 per row / 112 chrome / 1,662 per page**. Every screen task measures before it mounts.
- **`api.js:1-4`:** the client never computes a number the server owns.
- **REQ-COL-075 / Data Model v2.3 §3:** `payment_status` keeps its five values; `payment_status` and `dc_status` stay two fields; `StatusPair` is not modified.
- **PKD-001 / decision C3:** `backend/app/integrations/peak.py` keeps exactly four public functions and PEAK writes stay `DRAFT_ONLY`. Round A never imports or edits that module.
- **Raw-body uploads only** (`routers/imports.py` shape): `X-Volt-Filename` beside the body, `Content-Length` pre-check plus a running cap over `request.stream()`. `python-multipart` is not installed and an `UploadFile` parameter stops the app booting.
- **Honesty rules:** a configured-but-unreachable dependency refuses; an unconfigured one is labelled; every refusal is an RFC 9457 problem with `message_th`; indicative figures are badged where shown; nothing falls back silently.
- **PDPA (design F5, F7, F9):** the 13-digit id on the PEAK report is used in-run only and **never written** to any table, log or run receipt. Attachment bytes live in Postgres, never on disk, never logged.
- **Strings:** user-facing text goes in an `i18n-*.js` table (EN + TH; `i18n.test.js` checks parity and interpolation slots), never in `prefs.jsx`'s `DICT`.
- **Shared branch:** other sessions commit to `design-team` mid-run. Work in a worktree off the Task 0 commit with its own test database (`VOLT_TEST_PG_URL`); re-check `git log --oneline -8` before every baseline measurement.
- **Python:** keep 3.9-safe syntax (no `match`, no `X | Y` type unions at runtime) until the platform branch's Stage 0 merge switches the shared venv.

## Decisions this plan is cut to

The plan assumes the recommended option of every design §4 row. If Arina rules otherwise, only the tasks that cite the row are re-cut.

| Row | Assumed | Tasks that depend on it |
|---|---|---|
| F1 | EXACT rungs apply on "apply"; CANDIDATE and UNMATCHED wait for a person | 3, 4, 6, 12 |
| F2 | PEAK facts drive `payment_status_system` for a linked customer (`settings.peak_report_drives_status = True`) | 11 |
| F3 | A PEAK receipt is recorded `is_allocated = True` for PEAK-sourced receipts only (`settings.peak_report_allocates = True`); the engine's own arrears are **not** re-allocated in Round A | 8 |
| F4 | `landing.peak_invoice` + `records.identity_link`, durable | 1, 4, 7 |
| F5 | 13-digit id in-run only, never stored | 2, 3, 4 |
| F6 | `NEW_ONLY` default; `OVERWRITE` under ขั้นสูง; proposals listed | 15, 16, 17 |
| F7 | `records.attachment` in Postgres, 10 MB/file, 5 files/note | 20, 21, 22 |
| F8 | format rules + `RULES_ONLY` label + optional ClamAV port (`CLAMAV_HOST`/`CLAMAV_PORT`) | 21 |
| F17 | edits 35–39 available, measured before spending | 13, 19, 24 |
| F18 | worktree + own DB; the staged weekly work committed first | 0 |

## File structure (Round A)

**Backend — created**

| File | One job |
|---|---|
| `backend/app/pipelines/peak_report.py` | Parse the PEAK invoice report (csv/xlsx) into normalised invoice records. Pure. |
| `backend/app/pipelines/peak_match.py` | The match ladder: one verdict per invoice. Pure. |
| `backend/app/pipelines/peak_links.py` | The identity-link register in `records.identity_link` (load, confirm, retire, list). |
| `backend/app/pipelines/peak_writer.py` | One PEAK import_run: `landing.peak_invoice` rows, the receipt, apply, and the read the book uses. |
| `backend/app/pipelines/peak_service.py` | The run sequence, once, for the upload door. |
| `backend/app/routers/peak_pipeline.py` | `/v1/pipelines/peak-report/*` — Manager-only writes, readable lists. |
| `backend/app/payment_position.py` | The served block: paid/open counts, oldest unpaid, last money in, source, as-of, stale. |
| `backend/app/attachments/__init__.py`, `guard.py`, `store.py`, `scanner.py` | The file guard (format rules), the store (Postgres bytea, memory fallback labelled), the scanner port (ClamAV / rules-only). |
| `backend/app/routers/attachments.py` | `POST /v1/attachments`, `GET /v1/attachments/{uid}`, `POST /v1/attachments/{uid}:delete`. |
| `backend/tests/test_peak_report.py`, `test_peak_match.py`, `test_peak_writer.py`, `test_peak_service.py`, `test_peak_router.py`, `test_peak_book.py`, `test_payment_position.py` (extend), `test_import_new_only.py`, `test_attachments_guard.py`, `test_attachments_store.py`, `test_attachments_router.py`, `test_contact_notes.py` | One test file per unit. |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/schema.sql` | `PEAK` in `import_run.source_system`; `landing.peak_invoice`; schema `records` with `identity_link` and `attachment`. |
| `backend/app/migrate.py` | `records` added to the runtime grants. |
| `backend/app/config.py` | `peak_report_allocates`, `peak_report_drives_status`, `payment_position_stale_days`, `attachment_max_bytes`, `attachments_per_note`. |
| `backend/app/pipelines/runs.py` | `latest(kind=None)`. |
| `backend/app/book_source.py` | The `peak` block per customer from the last applied PEAK run. |
| `backend/app/main.py` | `reload_book()`; the two new routers included. |
| `backend/app/journey.py` | `_seed_peak_invoices`, `reseed_peak`; the sheet path skipped where PEAK facts exist. |
| `backend/app/payment_summary.py` | `peak_cycles` overlay, `source` per contract, provenance that says which. |
| `backend/app/routers/today.py` | `payment_position` on the case and the book row; `peak_cycles` passed to the summary; the `position` filter; notes routes. |
| `backend/app/routers/journey.py` | `payment_position` on the work item. |
| `backend/app/cases.py` | `_payment_status` reads PEAK facts; `follow_system_for_all`; contact notes. |
| `backend/app/pipelines/writer.py`, `service.py`, `routers/pipelines.py` | `mode` (NEW_ONLY / OVERWRITE), proposals, the three counts. |

**Frontend — created:** `components/PeakReportCard.jsx` (+ test), `components/PaymentPosition.jsx` (+ test), `components/AttachmentField.jsx` (+ test), `components/DrawerHistory.jsx` (+ test).

**Frontend — modified:** `api.js`, `screens/DataSourcesMigration.jsx`, `screens/CustomerCase.jsx`, `screens/Today.jsx`, `screens/WorkBook.jsx`, `components/PaymentOverview.jsx`, `components/CaseContactDrawer.jsx`, `i18n-admin.js`, `i18n-ops.js`, `i18n-journey.js`, `i18n-today.js`, `journey.css` (tokens only).

---

# Round A — journey and system

## Task 0: Measure, isolate, and clear the two blockers

This task writes no product code. Its output is three numbers, a worktree, and two decisions Arina has to make before Task 1 can run.

**Files:** none in the product tree.

- [ ] **Step 1: Confirm nobody else moved the branch since this plan was written**

Run: `git log --oneline -8 && git status --short | wc -l`
Expected: HEAD `f8acc2e` (or newer — if newer, read the new commits before continuing; they are another session's). The count of uncommitted paths was 78 on 2026-09-15.

- [ ] **Step 2: Blocker A — the rules file.** The staged `docs/odoo-comparison/odoo_compare.md` replaces the seven parsed tables with a three-scenario note. `pipelines/rules.py` cannot read it, which is why six `test_pipeline_*` tests fail and two error. WP2 needs the join table.

Run: `git show HEAD:docs/odoo-comparison/odoo_compare.md > /tmp/rules_head.md && git diff --cached --stat -- docs/odoo-comparison/odoo_compare.md`
Expected: the HEAD copy has headings `## 1. Join` … `## 7.`; the staged copy shows as modified.

**Ask Arina (do not decide alone):** restore the seven tables from HEAD and keep her three scenarios as a new `## 0. Action criteria` section at the top (recommended — the scenarios are exactly WP2's NEW_ONLY rule in words), or keep the note as it is and write the join keys into code. **Answer (Arina, 2026-09-15): restore the tables; the scenarios kept verbatim as §0 — done in 2297870.**

- [ ] **Step 3: Blocker B — the staged weekly work.** `git status` shows the weekly overview build (`reports.py`, `weekly_export.py`, `xlsx_writer.py`, `WeeklyOverview.jsx`, `weekly.css`, the tests) **staged and uncommitted**. It is another session's build. Ask Arina whether that session commits it, or this build commits it as its first commit with the message `feat(reports): weekly overview and editions (staged build of 2026-09-14)`. **Answer: not ruled; Round A branches from f8acc2e and leaves the staged work untouched in the main checkout (ledger ruling).** Nothing in Round A starts on top of uncommitted files.

- [ ] **Step 4: Make the worktree and its own database**

Run:
```bash
git worktree add /Users/parattakorn/volt-debt-worktrees/feedback-r1 -b feedback-r1
cd /Users/parattakorn/volt-debt-worktrees/feedback-r1
ln -s /Users/parattakorn/volt-debt-prototype/frontend/node_modules frontend/node_modules
python3 - <<'PY'
import sys; sys.path.insert(0, 'scripts')
import pg_local
pg_local.server().psql('create database volt_feedback_r1;')
PY
export VOLT_TEST_PG_URL="postgresql+psycopg://postgres:@/volt_feedback_r1?host=$HOME/.volt-postgres/data"
```
Expected: a worktree on branch `feedback-r1` from the Task 0 HEAD; the database exists. (The memory note on the two local databases is why: `volt_test` is shared and gets poisoned.)

- [ ] **Step 5: Run the backend suite and record the count**

Run: `cd backend && python -m pytest --continue-on-collection-errors`
Expected: a pass/skip/fail count. **Run it WITHOUT `-q`.** With Blocker A unresolved expect 6 failed + 2 errors in `test_pipeline_*`; with it resolved expect none. Write the numbers here:

| suite | baseline (date, HEAD) |
|---|---|
| backend | **847 passed, 11 skipped** (114s) — 2026-09-15 on 2297870 |
| frontend | **643 passed, 59 files** (11.4s) |
| e2e | **31 checks, 31 passed** · `verify_all.sh` EVERYTHING PASSED |
| density: CustomerCase pre-contact / worked | 75 / 94 without the overview · **104 of 104 / 123 of 123 with the overview** (at cap) |
| density: Today per-row / chrome / page | **31 of 31 / 112 of 112 / 1,662 of 1,662** (at cap) |

- [ ] **Step 6: Run the frontend suite, the density files alone, and the harness**

Run: `cd frontend && npx vitest run && npx vitest run src/density.test.jsx src/today-density.test.jsx && cd .. && ./scripts/verify_all.sh`
Expected: PASS; the density files print the measured `visible` per section — copy the pre-contact and worked totals into the table above, and Today's per-row, chrome and page totals.

- [ ] **Step 7: Commit the measurement into this plan (repo copy) and the vault copy**

```bash
git add docs/archive/superpowers/plans/2026-09-15-feedback-round-1.md
git commit -m "docs(plan): feedback round 1 — measured baseline before Round A"
```

---

## WP1 — PEAK invoice reconciliation

### Task 1: Schema — `PEAK` runs, `landing.peak_invoice`, schema `records`

**Files:**
- Modify: `backend/app/schema.sql` (append after the `audit` block)
- Modify: `backend/app/migrate.py:100-105` (`RUNTIME_GRANTS`)
- Test: `backend/tests/test_peak_writer.py` (create)

**Interfaces:**
- Produces: table `landing.peak_invoice` (columns below), table `records.identity_link`, and `'PEAK'` accepted by `landing.import_run.source_system`. Consumed by Tasks 4, 7.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_peak_writer.py
"""One PEAK import_run: the rows, the receipt, apply, and the read the book uses.
Feedback Round 1 / WP1 (design note 10 §3, F4)."""
import pytest
from sqlalchemy import text

from app import landing, migrate


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    yield pg_conn
    # `records` is outside the schemas conftest truncates (deliberately — it must
    # outlive a deploy), so this file cleans its own rows.
    pg_conn.execute(text("delete from records.identity_link"))


def test_the_schema_accepts_a_peak_run_and_holds_its_invoices(schema):
    run = landing.start_run(schema, "PEAK", meta={"report_as_of": "2026-09-14"})
    schema.execute(text(
        "insert into landing.peak_invoice (import_run_id, doc_no, doc_kind, status, verdict, lines) "
        "values (:r, 'IVT-20260700089', 'IVT', 'PAID', 'UNMATCHED', '[]'::jsonb)"), {"r": run})
    assert schema.execute(text("select count(*) from landing.peak_invoice")).scalar() == 1


def test_the_link_register_allows_one_active_link_per_contact_code(schema):
    schema.execute(text(
        "insert into records.identity_link (contact_code, customer_no, rule, confirmed_by) "
        "values ('99999000328', '28005096535', 'PERSON', 'settasak')"))
    with pytest.raises(Exception):
        schema.execute(text(
            "insert into records.identity_link (contact_code, customer_no, rule, confirmed_by) "
            "values ('99999000328', '28000000001', 'PERSON', 'settasak')"))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_peak_writer.py -v`
Expected: FAIL — `landing.import_run` refuses `'PEAK'` (check constraint) and `landing.peak_invoice` does not exist.

- [ ] **Step 3: Append the schema**

Append to `backend/app/schema.sql`:

```sql
-- Feedback Round 1 / WP1 (vault note 10 §3, F4). The PEAK invoice report lands
-- beside the sheet and Odoo under its own source. Postgres named the inline check
-- import_run_source_system_check; dropped and re-added by name so an existing
-- database converges (the audit block above does the same for actor_source).
ALTER TABLE landing.import_run DROP CONSTRAINT IF EXISTS import_run_source_system_check;
ALTER TABLE landing.import_run ADD CONSTRAINT import_run_source_system_check
    CHECK (source_system IN ('SHEET','ODOO','PEAK'));

-- One row per PEAK invoice (lines folded into jsonb), run-scoped like every landing
-- row. The 13-digit id on the report is NOT a column here, by ruling F5.
CREATE TABLE IF NOT EXISTS landing.peak_invoice (
    import_run_id    bigint  NOT NULL REFERENCES landing.import_run(id),
    doc_no           text    NOT NULL,
    doc_kind         text    NOT NULL,
    issued_on        date,
    due_on           date,
    reference        text,
    system_reference text,
    contact_code     text,
    customer_name    text,
    status           text    NOT NULL CHECK (status IN ('PAID','OVERDUE','AWAITING','DRAFT')),
    cycle_n          int,
    cycle_of         int,
    product_group    text,
    amount_total     numeric(14,2),
    amount_due       numeric(14,2),
    amount_awaiting  numeric(14,2),
    paid_on          date,
    paid_channel     text,
    paid_amount      numeric(14,2),
    receipt_no       text,
    note             text,
    lines            jsonb   NOT NULL DEFAULT '[]'::jsonb,
    verdict          text    NOT NULL CHECK (verdict IN ('EXACT','CANDIDATE','UNMATCHED','REJECTED')),
    rule             text,
    customer_no      text,
    candidates       jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (import_run_id, doc_no)
);
CREATE INDEX IF NOT EXISTS peak_invoice_customer_idx ON landing.peak_invoice (customer_no);
CREATE INDEX IF NOT EXISTS peak_invoice_contact_idx  ON landing.peak_invoice (contact_code);

-- Schema records: the product's memory. Not app (per-tester, discarded on deploy,
-- truncated by the test harness on principle) and not audit (append-only).
CREATE SCHEMA IF NOT EXISTS records;

CREATE TABLE IF NOT EXISTS records.identity_link (
    uid           bigserial   PRIMARY KEY,
    contact_code  text        NOT NULL,
    customer_no   text        NOT NULL,
    contract_uid  text,
    rule          text        NOT NULL,
    confirmed_by  text        NOT NULL,
    confirmed_at  timestamptz NOT NULL DEFAULT now(),
    reason        text,
    retired_at    timestamptz,
    retired_by    text
);
-- One ACTIVE link per contact code; a retired one stays as history.
CREATE UNIQUE INDEX IF NOT EXISTS identity_link_active_idx
    ON records.identity_link (contact_code) WHERE retired_at IS NULL;
```

In `backend/app/migrate.py`, change every `landing, app` inside `RUNTIME_GRANTS` to `landing, app, records` (four strings).

- [ ] **Step 4: Run it and watch it pass**

Run: `cd backend && python -m pytest tests/test_peak_writer.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 5: Run every Postgres-backed test to prove the constraint swap converges**

Run: `cd backend && python -m pytest tests/test_landing.py tests/test_pipeline_writer.py tests/test_audit_store.py -v`
Expected: PASS (the `ALTER … DROP CONSTRAINT IF EXISTS` re-runs cleanly on a database that already has it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schema.sql backend/app/migrate.py backend/tests/test_peak_writer.py
git commit -m "feat(schema): PEAK import runs, landing.peak_invoice, and the records schema with identity links"
```

---

### Task 2: The parser — `pipelines/peak_report.py`

**Files:**
- Create: `backend/app/pipelines/peak_report.py`
- Test: `backend/tests/test_peak_report.py` (create)

**Interfaces:**
- Consumes: `app.imports.sniff_kind(raw) -> "XLSX" | "OLE" | "MAYBE_CSV"`, `app.imports.read_xlsx(raw) -> [{"name", "rows"}]`, `app.imports.decode_csv(raw) -> (encoding, text)`.
- Produces: `peak_report.parse(raw: bytes, filename: str | None) -> dict` with keys `report_as_of` (ISO date or None), `header_row` (int), `lines` (list), `invoices` (list of the record below), `rejected` (list of `{"row", "code", "value"}`); raises `peak_report.ReportError(code, detail, detail_th)` when the header cannot be found. Consumed by Tasks 3, 4, 5.

Invoice record:

```python
{"doc_no": "IVT-20260700089", "doc_kind": "IVT", "issued_on": "2026-07-11", "due_on": "2026-07-18",
 "reference": "99999000328", "system_reference": None, "contact_code": "99999000328",
 "customer_name": "Somchai Tamdee", "tax_id_13": "1234567890121",   # in-run only (F5)
 "status": "PAID", "cycle": {"n": 14, "of": 48} or None, "product_group": "Solar Leasing" or None,
 "amount_total": "13060.45", "amount_due": "13060.45", "amount_awaiting": "0.00",
 "payment": {"on": "2026-07-16", "channel": "ธ.กสิกรไทย ออมทรัพย์", "amount": "13060.45", "receipt_no": "RE-20260700272"} or None,
 "note": "…", "lines": [{"line_no": 1, "product_code": "P00004", "description": "…", "amount": "8399.00"}]}
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_report.py
"""The PEAK invoice report, parsed. Column names are the report's own Thai headings
(measured on the 2026-09-14 export: 56 columns, header on row 11)."""
import pytest

from app import xlsx_writer
from app.pipelines import peak_report

HEADER = ["ลำดับที่", "เลขที่เอกสาร", "วันที่ออก", "วันที่ครบกำหนด", "อ้างอิง", "อ้างอิงจากระบบ", "บันทึกบัญชี",
          "สถานะ", "รหัสผู้ติดต่อ", "ชื่อลูกค้า", "เลขที่ 13 หลัก", "สาขา", "ประเภทราคา", "ใบกำกับภาษี",
          "สกุลเงิน", "อัตราแลกเปลี่ยน", "รายการที่", "รหัสสินค้า/บริการ", "ชื่อสินค้า/บริการ", "ผังบัญชี",
          "คำอธิบาย", "จำนวน", "หน่วย", "ราคา", "ส่วนลด", "มูลค่าก่อนภาษี", "ประเภทภาษี", "ยอด VAT",
          "หัก ณ ที่จ่าย", "ส่วนลดรวม", "เงินมัดจำ", "ไม่มี VAT", "VAT 0%", "VAT 7%", "ยอด VAT", "ทั้งหมด",
          "หัก ณ ที่จ่าย", "ต้องชำระ", "วันที่", "เลขที่ช่องทางการเงิน", "ช่องทางการชำระเงิน", "จำนวนเงิน",
          "e-WHT", "มูลค่ารอรับชำระ", "บันทึกบัญชี", "เลขที่ใบเสร็จ", "กลุ่มใหญ่", "กลุ่มย่อย", "%", "หมายเหตุ",
          "ไฟล์แนบ", "แท็ก", "ผู้สร้าง", "วันที่สร้าง", "ผู้อนุมัติ", "วันที่อนุมัติ"]


def _line(**over):
    row = {h: "" for h in HEADER}
    row.update({"ลำดับที่": "1", "เลขที่เอกสาร": "IVT-20260700089", "วันที่ออก": "11/07/2026",
                "วันที่ครบกำหนด": "18/07/2026", "อ้างอิง": "99999000328", "สถานะ": "รับชำระแล้ว",
                "รหัสผู้ติดต่อ": "99999000328", "ชื่อลูกค้า": "Somchai Tamdee", "เลขที่ 13 หลัก": "1234567890121",
                "รายการที่": "1", "รหัสสินค้า/บริการ": "P00004",
                "ชื่อสินค้า/บริการ": "Solar Rooftop (On-grid) 3 Phase_10kWp",
                "คำอธิบาย": "Solar Rooftop (On-grid) 3 Phase_10kWp Installment_M14/48",
                "ราคา": "8,399.00", "ทั้งหมด": "13060.45", "ต้องชำระ": "13060.45", "มูลค่ารอรับชำระ": "0.0",
                "วันที่": "16/07/2026", "ช่องทางการชำระเงิน": "Beam 0001", "จำนวนเงิน": "13060.45",
                "เลขที่ใบเสร็จ": "RE-20260700272", "กลุ่มใหญ่": "โครงการ", "กลุ่มย่อย": "Solar Leasing"})
    row.update(over)
    return row


def _report(lines, preamble=10):
    """The report as PEAK writes it: ten preamble rows, then the header, then lines.
    Duplicate headings (ยอด VAT twice) are kept — the parser must take the first."""
    rows = [["รายงานใบแจ้งหนี้"] + [""] * (len(HEADER) - 1)] * preamble
    rows.append(list(HEADER))
    for ln in lines:
        rows.append([ln.get(h, "") for h in HEADER])
    return xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้", "rows": rows}])


FILENAME = "invoice_บริษัท_โวลต์_จำกัด_export_as_of_20240101_20260914_20260914_155330.xlsx"


def test_it_finds_the_header_row_and_reads_one_invoice():
    out = peak_report.parse(_report([_line()]), FILENAME)
    assert out["header_row"] == 10
    assert out["report_as_of"] == "2026-09-14"
    inv = out["invoices"][0]
    assert inv["doc_no"] == "IVT-20260700089" and inv["doc_kind"] == "IVT"
    assert inv["issued_on"] == "2026-07-11" and inv["due_on"] == "2026-07-18"
    assert inv["status"] == "PAID"
    assert inv["contact_code"] == "99999000328" and inv["reference"] == "99999000328"
    assert inv["cycle"] == {"n": 14, "of": 48}
    assert inv["amount_due"] == "13060.45" and inv["amount_awaiting"] == "0.00"
    assert inv["payment"] == {"on": "2026-07-16", "channel": "Beam 0001",
                              "amount": "13060.45", "receipt_no": "RE-20260700272"}
    assert inv["product_group"] == "Solar Leasing"
    assert inv["lines"][0]["product_code"] == "P00004"


def test_lines_of_one_invoice_fold_into_one_record():
    out = peak_report.parse(_report([_line(), _line(**{"รายการที่": "2", "รหัสสินค้า/บริการ": "P00042",
                                                    "ชื่อสินค้า/บริการ": "Late Fee (No VAT)",
                                                    "คำอธิบาย": "Late Fee M11 (94 days)", "ราคา": "2,368.52"})]))
    assert len(out["invoices"]) == 1
    assert [l["product_code"] for l in out["invoices"][0]["lines"]] == ["P00004", "P00042"]


def test_every_status_the_report_uses_is_mapped_and_an_unknown_one_is_rejected_by_name():
    lines = [_line(**{"เลขที่เอกสาร": "IV-1", "สถานะ": "เกินเวลารับชำระ"}),
             _line(**{"เลขที่เอกสาร": "IV-2", "สถานะ": "รอชำระ"}),
             _line(**{"เลขที่เอกสาร": "IV-3", "สถานะ": "ร่าง"}),
             _line(**{"เลขที่เอกสาร": "IV-4", "สถานะ": "ยกเลิก"})]
    out = peak_report.parse(_report(lines))
    assert [i["status"] for i in out["invoices"]] == ["OVERDUE", "AWAITING", "DRAFT"]
    assert out["rejected"] == [{"row": 15, "code": "status_unknown", "value": "ยกเลิก"}]


def test_a_missing_required_heading_refuses_and_names_it():
    bad = [h if h != "อ้างอิง" else "Ref" for h in HEADER]
    rows = [["x"] * len(HEADER)] * 3 + [bad] + [[_line().get(h, "") for h in HEADER]]
    raw = xlsx_writer.workbook([{"name": "r", "rows": rows}])
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(raw)
    assert exc.value.code == "header_not_found"
    assert "อ้างอิง" in exc.value.detail


def test_no_cycle_mark_means_no_cycle_not_a_guess():
    inv = peak_report.parse(_report([_line(**{"คำอธิบาย": "Uninstall fee"})]))["invoices"][0]
    assert inv["cycle"] is None


def test_the_report_date_comes_from_the_file_name_or_is_none():
    assert peak_report.report_as_of(FILENAME) == "2026-09-14"
    assert peak_report.report_as_of("invoices.xlsx") is None


def test_a_csv_export_reads_the_same_as_the_xlsx():
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    for _ in range(2):
        w.writerow(["รายงานใบแจ้งหนี้"] + [""] * (len(HEADER) - 1))
    w.writerow(HEADER)
    w.writerow([_line().get(h, "") for h in HEADER])
    out = peak_report.parse(("\ufeff" + buf.getvalue()).encode("utf-8"), "x.csv")
    assert out["invoices"][0]["doc_no"] == "IVT-20260700089"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.peak_report'`.

- [ ] **Step 3: Write the parser**

```python
# backend/app/pipelines/peak_report.py
"""The PEAK invoice report ("รายงานใบแจ้งหนี้"), parsed into invoice records.

Feedback Round 1 / WP1 (vault note 10 §2.1, §3). Measured on the 2026-09-14 export:
7,999 lines, 7,638 invoices, header on row 11, 56 columns, three headings repeated.

Pure: bytes in, records out. No clock, no database, no network. The reader is
app.imports (ruling 36: never a second csv/xlsx parser).

Two refusals are deliberate. A missing required heading refuses the whole file and
names the heading, because a column PEAK moved would otherwise shift silently into
its neighbour. An unknown status value rejects that row and prints the value,
because mapping it to the nearest known one would be a confident wrong number.
"""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

from .. import imports as imports_domain

REQUIRED = ("เลขที่เอกสาร", "อ้างอิง", "สถานะ", "รหัสผู้ติดต่อ")

STATUS_MAP = {"รับชำระแล้ว": "PAID", "เกินเวลารับชำระ": "OVERDUE", "รอชำระ": "AWAITING", "ร่าง": "DRAFT"}

# Column heading -> record key. Headings that appear twice (ยอด VAT, หัก ณ ที่จ่าย,
# บันทึกบัญชี) are taken at their FIRST index; the second copy is the receipt side of
# the report and is not read.
COLUMNS = {
    "เลขที่เอกสาร": "doc_no", "วันที่ออก": "issued_on", "วันที่ครบกำหนด": "due_on",
    "อ้างอิง": "reference", "อ้างอิงจากระบบ": "system_reference", "สถานะ": "status_th",
    "รหัสผู้ติดต่อ": "contact_code", "ชื่อลูกค้า": "customer_name", "เลขที่ 13 หลัก": "tax_id_13",
    "รายการที่": "line_no", "รหัสสินค้า/บริการ": "product_code", "ชื่อสินค้า/บริการ": "product_name",
    "คำอธิบาย": "description", "ราคา": "price", "ทั้งหมด": "amount_total", "ต้องชำระ": "amount_due",
    "มูลค่ารอรับชำระ": "amount_awaiting", "วันที่": "paid_on", "ช่องทางการชำระเงิน": "paid_channel",
    "จำนวนเงิน": "paid_amount", "เลขที่ใบเสร็จ": "receipt_no", "กลุ่มย่อย": "product_group",
    "หมายเหตุ": "note",
}

_AS_OF = re.compile(r"export_as_of_\d{8}_(\d{4})(\d{2})(\d{2})")
_CYCLE = re.compile(r"M\s?(\d+)\s*/\s*(\d+)")
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


class ReportError(Exception):
    def __init__(self, code, detail, detail_th):
        super().__init__(detail)
        self.code, self.detail, self.detail_th = code, detail, detail_th


def report_as_of(filename):
    """PEAK names the export "…export_as_of_<from>_<to>_<stamp>.xlsx"; <to> is the
    day the report is true for. None when the name does not say — never today."""
    m = _AS_OF.search(filename or "")
    return "%s-%s-%s" % m.groups() if m else None


def _table(raw):
    kind = imports_domain.sniff_kind(raw)
    if kind == "XLSX":
        tabs = imports_domain.read_xlsx(raw)
        return [list(r) for r in (tabs[0]["rows"] if tabs else [])]
    if kind == "OLE":
        raise ReportError("unreadable", "legacy .xls or a password-protected workbook",
                          "ไฟล์เป็น .xls เก่าหรือติดรหัสผ่าน — ส่งออกเป็น .xlsx หรือ .csv")
    _enc, text = imports_domain.decode_csv(raw)
    return list(csv.reader(io.StringIO(text)))


def _cell(row, i):
    if i is None or i >= len(row) or row[i] is None:
        return ""
    return str(row[i]).strip()


def _find_header(table):
    for i, row in enumerate(table):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if all(h in cells for h in REQUIRED):
            index = {}
            for pos, name in enumerate(cells):
                index.setdefault(name, pos)          # first occurrence wins
            return i, index
    raise ReportError("header_not_found",
                      "no row carries all of the headings %s" % ", ".join(REQUIRED),
                      "ไม่พบแถวหัวตารางที่มีคอลัมน์ %s ครบ" % ", ".join(REQUIRED))


def _date(text):
    m = _DATE.match(text or "")
    if not m:
        return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text or "") else None
    d, mo, y = m.groups()
    return "%s-%02d-%02d" % (y, int(mo), int(d))


def _money(text):
    if text in (None, ""):
        return None
    try:
        return str(Decimal(str(text).replace(",", "")).quantize(Decimal("0.01")))
    except InvalidOperation:
        return None


def _cycle(*texts):
    for t in texts:
        m = _CYCLE.search(t or "")
        if m:
            return {"n": int(m.group(1)), "of": int(m.group(2))}
    return None


def parse(raw, filename=None):
    table = _table(raw)
    header_row, index = _find_header(table)
    col = {key: index.get(name) for name, key in COLUMNS.items()}
    lines, rejected = [], []
    for n, row in enumerate(table[header_row + 1:], start=header_row + 2):   # 1-based sheet row
        doc_no = _cell(row, col["doc_no"])
        if not doc_no:
            continue
        status_th = _cell(row, col["status_th"])
        status = STATUS_MAP.get(status_th)
        if status is None:
            rejected.append({"row": n, "code": "status_unknown", "value": status_th})
            continue
        lines.append({key: _cell(row, i) for key, i in col.items()} | {"status": status, "sheet_row": n})
    return {"report_as_of": report_as_of(filename), "header_row": header_row,
            "lines": lines, "invoices": group(lines), "rejected": rejected}


def group(lines):
    """Lines share doc_no; the invoice-level cells repeat on every line and are
    read from the first. Order of first appearance is kept."""
    by_doc, order = {}, []
    for ln in lines:
        doc = ln["doc_no"]
        if doc not in by_doc:
            order.append(doc)
            paid_on = _date(ln["paid_on"])
            by_doc[doc] = {
                "doc_no": doc, "doc_kind": doc.split("-")[0] if "-" in doc else doc,
                "issued_on": _date(ln["issued_on"]), "due_on": _date(ln["due_on"]),
                "reference": ln["reference"] or None, "system_reference": ln["system_reference"] or None,
                "contact_code": ln["contact_code"] or None, "customer_name": ln["customer_name"] or None,
                "tax_id_13": ln["tax_id_13"] or None,            # in-run only; never written (F5)
                "status": ln["status"], "cycle": None,
                "product_group": ln["product_group"] or None,
                "amount_total": _money(ln["amount_total"]), "amount_due": _money(ln["amount_due"]),
                "amount_awaiting": _money(ln["amount_awaiting"]) or "0.00",
                "payment": ({"on": paid_on, "channel": ln["paid_channel"] or None,
                             "amount": _money(ln["paid_amount"]), "receipt_no": ln["receipt_no"] or None}
                            if paid_on or ln["receipt_no"] else None),
                "note": ln["note"] or None, "lines": [],
            }
        inv = by_doc[doc]
        if inv["cycle"] is None:
            inv["cycle"] = _cycle(ln["description"], ln["product_name"])
        inv["lines"].append({"line_no": int(float(ln["line_no"])) if ln["line_no"] else len(inv["lines"]) + 1,
                             "product_code": ln["product_code"] or None,
                             "description": ln["description"] or None, "amount": _money(ln["price"])})
    return [by_doc[d] for d in order]
```

Note for the implementer: `dict | dict` needs Python 3.9 — the shared venv is 3.9.6, so it is allowed; if the tree is still on an older interpreter anywhere, replace it with `dict(..., **{...})`.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_report.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 5: Parse the real export once, locally, and paste the counts here**

Run: `cd backend && python -c "from app.pipelines import peak_report; o=peak_report.parse(open('/private/tmp/…/peak_export.xlsx','rb').read(), 'invoice_…export_as_of_20240101_20260914_….xlsx'); print(len(o['lines']), len(o['invoices']), len(o['rejected']), o['report_as_of'])"`
Expected: `7999 7638 1 2026-09-14` (the one rejected row is the blank-status trailer). If the numbers differ, the parser is wrong, not the file.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipelines/peak_report.py backend/tests/test_peak_report.py
git commit -m "feat(peak): parse the PEAK invoice report into invoice records, refusing what it cannot read"
```

---

### Task 3: The match ladder — `pipelines/peak_match.py`

**Files:**
- Create: `backend/app/pipelines/peak_match.py`
- Test: `backend/tests/test_peak_match.py` (create)

**Interfaces:**
- Consumes: invoice records from Task 2.
- Produces:
  - `peak_match.build_book_index(customers) -> dict` from objects carrying `customer_no`, `volt_id`, `phone_e164`, `display_name`, `name_roman` (the book's `Customer` fixtures, or dicts in tests).
  - `peak_match.build_odoo_index(rows) -> {vid: phone_digits}` from dicts with `volt_id`, `phone_e164`.
  - `peak_match.match(invoices, book, odoo, links) -> list[dict]`, one per invoice: `{"verdict": "EXACT"|"CANDIDATE"|"UNMATCHED", "rule": str|None, "customer_no": str|None, "candidates": [{"customer_no", "rule", "code"}]}`. `links` is `{contact_code: {"customer_no": ...}}` (Task 4).
  - Rule names: `LINK`, `CUSTOMER_NO`, `VOLT_ID`, `VOLT_ID_VIA_ODOO_PHONE`, `COMPOSITE`, `NAME`.
  Consumed by Tasks 4, 5.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_match.py
"""The match ladder (vault note 10 §3 WP1). Every rung is a test; the order of the
rungs is a test; what never auto-applies is a test."""
from app.pipelines import peak_match as pm

BOOK = pm.build_book_index([
    {"customer_no": "28005096535", "volt_id": "28005096535_Manop_มานพ ทดสอบ_IPW",
     "phone_e164": "+66812345678", "display_name": "มานพ ทดสอบ", "name_roman": "Manop"},
    {"customer_no": "28006083653", "volt_id": "99999000328_Somchai_สมชาย ทำดี_SLT",
     "phone_e164": "+66898765432", "display_name": "สมชาย ทำดี", "name_roman": "Somchai"},
])
ODOO = pm.build_odoo_index([{"volt_id": "VL0010239", "phone_e164": "0812345678"}])


def _inv(**over):
    base = {"doc_no": "IV-1", "reference": None, "contact_code": None, "customer_name": None}
    base.update(over)
    return base


def test_rung_1_an_eleven_digit_contact_code_is_the_customer_number():
    v = pm.match([_inv(contact_code="28005096535")], BOOK, ODOO, {})[0]
    assert v == {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": "28005096535", "candidates": []}


def test_rung_1_reads_the_reference_column_too():
    v = pm.match([_inv(reference="28005096535", contact_code="QO-20260600021")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "CUSTOMER_NO"


def test_rung_2_a_v_id_matches_the_books_volt_id_prefix_case_and_space_insensitively():
    v = pm.match([_inv(contact_code=" vc0010541 ")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "VOLT_ID" and v["customer_no"] == "28006083653"


def test_rung_3_a_v_id_the_book_lacks_goes_through_odoos_phone():
    v = pm.match([_inv(contact_code="VL0010239")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "VOLT_ID_VIA_ODOO_PHONE"
    assert v["customer_no"] == "28005096535"


def test_rung_0_a_confirmed_link_wins_over_every_other_rung():
    links = {"99999000328": {"customer_no": "28005096535"}}
    v = pm.match([_inv(contact_code="99999000328")], BOOK, ODOO, links)[0]
    assert v["rule"] == "LINK" and v["customer_no"] == "28005096535"


def test_rung_4_a_composite_code_is_a_candidate_never_an_exact_match():
    v = pm.match([_inv(contact_code="VL0010239,99999000328")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None
    assert {c["customer_no"] for c in v["candidates"]} == {"28005096535", "28006083653"}
    assert all(c["rule"].startswith("COMPOSITE") for c in v["candidates"])


def test_rung_4_repairs_a_suffix_and_a_short_code_but_still_only_proposes():
    assert pm.code_parts("VL0010696,697") == ["VL0010696", "VL0010697"]
    assert pm.code_parts("VC001059") == ["VC0001059"]
    v = pm.match([_inv(contact_code="VC001054,10541")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert any(c["code"] == "99999000328" for c in v["candidates"])


def test_rung_5_a_name_is_only_ever_a_candidate():
    v = pm.match([_inv(contact_code="QO-1", customer_name="คุณ มานพ  ทดสอบ")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["candidates"][0]["rule"] == "NAME"
    v = pm.match([_inv(contact_code="QO-1", customer_name="Mr. Somchai")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["candidates"][0]["customer_no"] == "28006083653"


def test_nothing_matches_means_unmatched_with_no_customer_invented():
    v = pm.match([_inv(contact_code="VRC0000022", customer_name="Nobody Here")], BOOK, ODOO, {})[0]
    assert v == {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_match.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the matcher**

```python
# backend/app/pipelines/peak_match.py
"""The match ladder: which customer a PEAK invoice belongs to, and by which rule.

Vault note 10 §2.1 measured why each rung exists: 612 of 645 V-id contact codes are
Odoo's crm.lead.volt_id (rung 3 bridges through Odoo's phone); 188 of 339 eleven-digit
codes equal a book customer_no (rung 1); 282 codes are composites like
"VL0010239,VC0010687" — the package-change trace (rung 4, candidates only); names are
Latin in PEAK and Thai in the book (rung 5, candidates only).

Pure. The indexes are built by the caller from whatever holds the book today.
EXACT is the only verdict that ever applies without a click (design F1).
"""
import re

V_ID = re.compile(r"^(VC|VRC|VL|VRL)(\d{7})$")
V_SHORT = re.compile(r"^(VC|VRC|VL|VRL)(\d{1,6})$")
ELEVEN = re.compile(r"^\d{11}$")
TITLES = re.compile(r"^(นาย|นางสาว|นาง|คุณ|บริษัท|mr\.?|mrs\.?|ms\.?|miss)\s*", re.IGNORECASE)


def normalise_code(text):
    return re.sub(r"\s+", "", str(text or "")).upper()


def normalise_name(text):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = TITLES.sub("", t)
    return t.lower()


def _digits(phone):
    d = re.sub(r"\D", "", str(phone or ""))
    if d.startswith("66") and len(d) == 11:
        d = "0" + d[2:]
    return d


def code_parts(text):
    """One code, or the parts of a composite, each repaired where the repair is
    unambiguous: a bare numeric suffix takes the previous part's prefix and length;
    a short V-id is zero-padded to seven digits."""
    parts = [p for p in re.split(r"[,\s;/]+", normalise_code(text)) if p]
    out, prev = [], None
    for p in parts:
        if p.isdigit() and prev and V_ID.match(prev) and len(p) < 7:
            p = prev[:len(prev) - len(p)] + p
        m = V_SHORT.match(p)
        if m and not V_ID.match(p):
            p = m.group(1) + m.group(2).zfill(7)
        out.append(p)
        prev = p if V_ID.match(p) else prev
    return out


def build_book_index(customers):
    idx = {"by_no": {}, "by_vid": {}, "by_phone": {}, "by_name": {}}
    for c in customers:
        get = (lambda k, o=c: o.get(k)) if isinstance(c, dict) else (lambda k, o=c: getattr(o, k, None))
        no = str(get("customer_no") or "")
        if not no:
            continue
        idx["by_no"][no] = no
        m = re.match(r"^(V[A-Z]{1,2}\d{7})", normalise_code(get("volt_id")))
        if m:
            idx["by_vid"][m.group(1)] = no
        ph = _digits(get("phone_e164"))
        if ph:
            idx["by_phone"][ph] = no
        for name in (get("display_name"), get("name_roman")):
            n = normalise_name(name)
            if n:
                idx["by_name"].setdefault(n, no)
    return idx


def build_odoo_index(rows):
    out = {}
    for r in rows:
        vid = normalise_code(r.get("volt_id"))
        ph = _digits(r.get("phone_e164") or r.get("phone"))
        if V_ID.match(vid) and ph:
            out[vid] = ph
    return out


def _exact(code, book, odoo):
    """Rungs 1–3 for one already-normalised code. (customer_no, rule) or (None, None)."""
    if ELEVEN.match(code) and code in book["by_no"]:
        return code, "CUSTOMER_NO"
    if V_ID.match(code):
        if code in book["by_vid"]:
            return book["by_vid"][code], "VOLT_ID"
        phone = odoo.get(code)
        if phone and phone in book["by_phone"]:
            return book["by_phone"][phone], "VOLT_ID_VIA_ODOO_PHONE"
    return None, None


def match_one(invoice, book, odoo, links):
    raw_codes = [invoice.get("contact_code"), invoice.get("reference")]
    for raw in raw_codes:
        code = normalise_code(raw)
        if code and code in links:
            return {"verdict": "EXACT", "rule": "LINK", "customer_no": links[code]["customer_no"], "candidates": []}
    for raw in raw_codes:
        code = normalise_code(raw)
        if not code:
            continue
        parts = code_parts(code)
        if len(parts) == 1 and parts[0] == code:
            no, rule = _exact(code, book, odoo)
            if no:
                return {"verdict": "EXACT", "rule": rule, "customer_no": no, "candidates": []}
    candidates = []
    for raw in raw_codes:
        code = normalise_code(raw)
        parts = code_parts(code) if code else []
        if len(parts) > 1 or (parts and parts[0] != code):
            for p in parts:
                no, rule = _exact(p, book, odoo)
                if no and not any(c["customer_no"] == no for c in candidates):
                    candidates.append({"customer_no": no, "rule": "COMPOSITE:" + rule, "code": p})
    name = normalise_name(invoice.get("customer_name"))
    if name:
        first = name.split(" ")[0]
        for key, no in book["by_name"].items():
            if (key == name or key == first) and not any(c["customer_no"] == no for c in candidates):
                candidates.append({"customer_no": no, "rule": "NAME", "code": invoice.get("customer_name")})
    if candidates:
        return {"verdict": "CANDIDATE", "rule": None, "customer_no": None, "candidates": candidates}
    return {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}


def match(invoices, book, odoo, links):
    return [match_one(inv, book, odoo, links or {}) for inv in invoices]
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_match.py -v`
Expected: PASS — 9 tests. If `test_rung_4_repairs…` fails on `"VC001054,10541"`, check `code_parts`: the first part pads to `VC0001054`, the suffix `10541` takes the prefix `VC` and the previous part's length → `99999000328`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/peak_match.py backend/tests/test_peak_match.py
git commit -m "feat(peak): the match ladder — exact by customer number, V-id and Odoo's phone; composites and names only propose"
```

---

### Task 4: The link register and the writer — `peak_links.py`, `peak_writer.py`

**Files:**
- Create: `backend/app/pipelines/peak_links.py`
- Create: `backend/app/pipelines/peak_writer.py`
- Test: `backend/tests/test_peak_writer.py` (extend)

**Interfaces:**
- Consumes: Task 1's tables; `landing.start_run / finish_run / get_run / serialize_run`; Task 2's invoice records; Task 3's verdicts.
- Produces:
  - `peak_links.load(conn) -> {code: {"uid", "customer_no", "contract_uid", "rule"}}` (active links, codes normalised)
  - `peak_links.confirm(conn, contact_code, customer_no, by, reason=None, rule="PERSON", contract_uid=None) -> dict`
  - `peak_links.retire(conn, uid, by) -> dict | None`
  - `peak_links.list_links(conn, include_retired=False) -> list[dict]`
  - `peak_writer.write(conn, parsed, verdicts, door="upload", filename=None, on_progress=None) -> dict` with `run_id, invoices, matched, candidates, unmatched, rejected, report_as_of, door`
  - `peak_writer.last_run(conn, applied=None) -> dict | None`
  - `peak_writer.apply_run(conn, run_id, by, allow_older=False) -> dict` (raises `peak_writer.WriterRefused(code, detail, detail_th)`)
  - `peak_writer.rows(conn, run_id, verdict=None, limit=100, offset=0) -> {"rows", "total", "limit", "offset"}`
  - `peak_writer.odoo_phone_rows(conn) -> list[{"volt_id", "phone_e164"}]`
  - `peak_writer.invoices_for_book(conn) -> {customer_no: {"report_as_of", "run_id", "invoices": [...]}}`
  Consumed by Tasks 5, 6, 8.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_peak_writer.py`)

```python
from app.pipelines import peak_links, peak_writer


def _parsed(*invoices, as_of="2026-09-14"):
    return {"report_as_of": as_of, "header_row": 10, "lines": [], "rejected": [], "invoices": list(invoices)}


def _inv(doc, code, status="PAID", cycle=None, payment=None, awaiting="0.00"):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code, "customer_name": "Someone",
            "tax_id_13": "1234567890121", "status": status, "cycle": cycle, "product_group": "Solar Leasing",
            "amount_total": "8399.00", "amount_due": "8399.00", "amount_awaiting": awaiting,
            "payment": payment, "note": None, "lines": [{"line_no": 1, "product_code": "P00004",
                                                          "description": "Installment_M14/48", "amount": "8399.00"}]}


EXACT = {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": "28005096535", "candidates": []}
CAND = {"verdict": "CANDIDATE", "rule": None, "customer_no": None,
        "candidates": [{"customer_no": "28005096535", "rule": "COMPOSITE:VOLT_ID", "code": "99999000328"}]}
NONE = {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}


def test_a_run_lands_every_invoice_with_its_verdict_and_never_the_13_digit_id(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), _inv("IV-2", "VL0010239,99999000328"),
                                               _inv("IV-3", "VRC0000022")), [EXACT, CAND, NONE], door="upload",
                               filename="export_as_of_20240101_20260914.xlsx")
    assert (result["invoices"], result["matched"], result["candidates"], result["unmatched"]) == (3, 1, 1, 1)
    cols = {r[0] for r in schema.execute(text(
        "select column_name from information_schema.columns where table_schema='landing' and table_name='peak_invoice'"))}
    assert "tax_id_13" not in cols
    meta = schema.execute(text("select meta from landing.import_run where id=:i"), {"i": result["run_id"]}).scalar()
    assert "1234567890121" not in json.dumps(meta)
    assert meta["report_as_of"] == "2026-09-14" and meta["door"] == "upload"


def test_a_staged_run_is_not_read_by_the_book_until_it_is_applied(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535")), [EXACT])
    assert peak_writer.invoices_for_book(schema) == {}
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    served = peak_writer.invoices_for_book(schema)
    assert served["28005096535"]["report_as_of"] == "2026-09-14"
    assert served["28005096535"]["invoices"][0]["doc_no"] == "IV-1"


def test_applying_an_older_report_over_a_newer_one_refuses_unless_allowed(schema):
    new = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-09-14"), [EXACT])
    peak_writer.apply_run(schema, new["run_id"], by="settasak")
    old = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-08-31"), [EXACT])
    with pytest.raises(peak_writer.WriterRefused) as exc:
        peak_writer.apply_run(schema, old["run_id"], by="settasak")
    assert exc.value.code == "report_older_than_applied"
    peak_writer.apply_run(schema, old["run_id"], by="settasak", allow_older=True)
    assert peak_writer.last_run(schema, applied=True)["id"] == old["run_id"]


def test_a_confirmed_link_lifts_a_candidate_row_into_the_book_without_a_re_run(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-2", "VL0010239,99999000328")), [CAND])
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    assert peak_writer.invoices_for_book(schema) == {}
    link = peak_links.confirm(schema, "vl0010239,vc0010541", "28005096535", by="settasak", reason="package change")
    assert link["contact_code"] == "VL0010239,99999000328"
    assert peak_writer.invoices_for_book(schema)["28005096535"]["invoices"][0]["rule"] == "LINK"
    peak_links.retire(schema, link["uid"], by="settasak")
    assert peak_writer.invoices_for_book(schema) == {}


def test_confirming_a_code_again_retires_the_earlier_link_and_keeps_it_as_history(schema):
    first = peak_links.confirm(schema, "99999000328", "28005096535", by="settasak")
    second = peak_links.confirm(schema, "99999000328", "28006083653", by="settasak", reason="wrong person")
    assert peak_links.load(schema)["99999000328"]["customer_no"] == "28006083653"
    history = peak_links.list_links(schema, include_retired=True)
    assert {l["uid"] for l in history} == {first["uid"], second["uid"]}


def test_rows_are_paged_by_verdict(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), _inv("IV-3", "VRC0000022")), [EXACT, NONE])
    page = peak_writer.rows(schema, result["run_id"], verdict="UNMATCHED", limit=10, offset=0)
    assert page["total"] == 1 and page["rows"][0]["doc_no"] == "IV-3"


def test_the_odoo_phone_rows_come_from_ok_runs_only(schema):
    run = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, run, "ODOO", {"volt_id": "VL0010239", "customer_no": "VL0010239",
                                                 "phone_e164": "0812345678", "source_refs": []})
    assert peak_writer.odoo_phone_rows(schema) == []
    landing.finish_run(schema, run, "OK")
    assert peak_writer.odoo_phone_rows(schema) == [{"volt_id": "VL0010239", "phone_e164": "0812345678"}]
```

Add `import json` at the top of the test file.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_writer.py -v`
Expected: FAIL — `ModuleNotFoundError` for `peak_links` / `peak_writer`.

- [ ] **Step 3: Write the link register**

```python
# backend/app/pipelines/peak_links.py
"""The identity-link register: what a person confirmed about which PEAK contact code
is which customer. records.identity_link (vault note 10 §3 WP1, F4).

Rung 0 of the ladder reads it at match time AND the book reads it at load time
(peak_writer.invoices_for_book), so confirming a link serves the invoices at once —
no re-run, no re-upload. Retiring keeps the row as history; only retired_at moves.
"""
from sqlalchemy import text

from .peak_match import normalise_code


def _row(r):
    d = dict(r)
    for k in ("confirmed_at", "retired_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


def load(conn):
    rows = conn.execute(text(
        "select uid, contact_code, customer_no, contract_uid, rule from records.identity_link "
        "where retired_at is null")).mappings().all()
    return {r["contact_code"]: dict(r) for r in rows}


def list_links(conn, include_retired=False):
    where = "" if include_retired else "where retired_at is null"
    rows = conn.execute(text("select * from records.identity_link %s order by uid" % where)).mappings().all()
    return [_row(r) for r in rows]


def confirm(conn, contact_code, customer_no, by, reason=None, rule="PERSON", contract_uid=None):
    code = normalise_code(contact_code)
    if not code or not customer_no:
        raise ValueError("a link needs a contact code and a customer number")
    conn.execute(text(
        "update records.identity_link set retired_at = now(), retired_by = :by "
        "where contact_code = :c and retired_at is null"), {"c": code, "by": by})
    row = conn.execute(text(
        "insert into records.identity_link (contact_code, customer_no, contract_uid, rule, confirmed_by, reason) "
        "values (:c, :n, :k, :r, :by, :why) returning *"),
        {"c": code, "n": str(customer_no), "k": contract_uid, "r": rule, "by": by, "why": reason}).mappings().one()
    return _row(row)


def retire(conn, uid, by):
    row = conn.execute(text(
        "update records.identity_link set retired_at = now(), retired_by = :by "
        "where uid = :u and retired_at is null returning *"), {"u": int(uid), "by": by}).mappings().first()
    return _row(row) if row else None
```

- [ ] **Step 4: Write the writer**

```python
# backend/app/pipelines/peak_writer.py
"""One PEAK import_run: the invoices with their verdicts, the receipt on the run,
the apply step, and the one read the book makes.

A run is STAGED when written and APPLIED when a person says so (design F1). Applied
is a mark on import_run.meta, never a status of its own: status stays the landing
schema's RUNNING/OK/FAILED, and book_source keeps reading only OK runs.

The 13-digit id is dropped here, before anything is written (F5).
"""
import json
from datetime import date, datetime

from sqlalchemy import text

from .. import landing
from .peak_match import normalise_code

SOURCE = "PEAK"
STORED = ("doc_no", "doc_kind", "issued_on", "due_on", "reference", "system_reference", "contact_code",
          "customer_name", "status", "product_group", "amount_total", "amount_due", "amount_awaiting", "note")


class WriterRefused(Exception):
    def __init__(self, code, detail, detail_th):
        super().__init__(detail)
        self.code, self.detail, self.detail_th = code, detail, detail_th


def _iso(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if isinstance(value, date) and not isinstance(value, datetime) else value.isoformat()
    return value


def write(conn, parsed, verdicts, door="upload", filename=None, on_progress=None):
    run = landing.start_run(conn, SOURCE, meta={"report_as_of": parsed.get("report_as_of"),
                                                 "door": door, "filename": filename})
    counts = {"EXACT": 0, "CANDIDATE": 0, "UNMATCHED": 0}
    for i, (inv, verdict) in enumerate(zip(parsed["invoices"], verdicts), start=1):
        params = {k: inv.get(k) for k in STORED}
        pay = inv.get("payment") or {}
        cycle = inv.get("cycle") or {}
        params.update(run=run, cycle_n=cycle.get("n"), cycle_of=cycle.get("of"),
                      paid_on=pay.get("on"), paid_channel=pay.get("channel"), paid_amount=pay.get("amount"),
                      receipt_no=pay.get("receipt_no"), lines=json.dumps(inv.get("lines") or [], ensure_ascii=False),
                      verdict=verdict["verdict"], rule=verdict.get("rule"), customer_no=verdict.get("customer_no"),
                      candidates=json.dumps(verdict.get("candidates") or [], ensure_ascii=False))
        conn.execute(text(
            "insert into landing.peak_invoice (import_run_id, doc_no, doc_kind, issued_on, due_on, reference, "
            "system_reference, contact_code, customer_name, status, cycle_n, cycle_of, product_group, amount_total, "
            "amount_due, amount_awaiting, paid_on, paid_channel, paid_amount, receipt_no, note, lines, verdict, rule, "
            "customer_no, candidates) values (:run, :doc_no, :doc_kind, cast(:issued_on as date), cast(:due_on as date), "
            ":reference, :system_reference, :contact_code, :customer_name, :status, :cycle_n, :cycle_of, "
            ":product_group, :amount_total, :amount_due, :amount_awaiting, cast(:paid_on as date), :paid_channel, "
            ":paid_amount, :receipt_no, :note, cast(:lines as jsonb), :verdict, :rule, :customer_no, "
            "cast(:candidates as jsonb)) on conflict (import_run_id, doc_no) do nothing"), params)
        counts[verdict["verdict"]] += 1
        if on_progress and i % 500 == 0:
            on_progress(landed=i)
    rejected = len(parsed.get("rejected") or [])
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"rejected": parsed.get("rejected") or [], "matched": counts["EXACT"],
                                   "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"]},
                                  ensure_ascii=False), "i": run})
    landing.finish_run(conn, run, "OK", row_counts={"read": len(parsed.get("lines") or []),
                                                    "landed": len(parsed["invoices"]), "rejected": rejected})
    return {"run_id": run, "invoices": len(parsed["invoices"]), "matched": counts["EXACT"],
            "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"], "rejected": rejected,
            "report_as_of": parsed.get("report_as_of"), "door": door}


def last_run(conn, applied=None):
    clause = ""
    if applied is True:
        clause = "and meta ? 'applied'"
    elif applied is False:
        clause = "and not (meta ? 'applied')"
    row = conn.execute(text(
        "select * from landing.import_run where source_system = :s and status = 'OK' %s "
        "order by id desc limit 1" % clause), {"s": SOURCE}).mappings().first()
    return landing.serialize_run(row) if row else None


def apply_run(conn, run_id, by, allow_older=False):
    run = landing.get_run(conn, run_id)
    if run is None or run.get("source_system") != SOURCE:
        raise WriterRefused("not_found", "no PEAK run %s" % run_id, "ไม่พบรอบนำเข้า PEAK นี้")
    current = last_run(conn, applied=True)
    if current and not allow_older:
        newer = (current.get("meta") or {}).get("report_as_of") or ""
        mine = (run.get("meta") or {}).get("report_as_of") or ""
        if mine and newer and mine < newer:
            raise WriterRefused("report_older_than_applied",
                                "report as of %s is older than the applied %s" % (mine, newer),
                                "รายงานนี้ (ณ %s) เก่ากว่ารายงานที่ใช้อยู่ (ณ %s) — ติ๊ก 'ใช้รายงานเก่ากว่า' หากตั้งใจ" % (mine, newer))
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"applied": {"by": by, "at": datetime.utcnow().isoformat() + "Z"}}), "i": int(run_id)})
    return landing.serialize_run(landing.get_run(conn, run_id))


def rows(conn, run_id, verdict=None, limit=100, offset=0):
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    clause = "and verdict = :v" if verdict else ""
    params = {"r": int(run_id), "lim": limit, "off": offset}
    if verdict:
        params["v"] = verdict
    total = conn.execute(text("select count(*) from landing.peak_invoice where import_run_id = :r %s" % clause),
                         {k: v for k, v in params.items() if k in ("r", "v")}).scalar() or 0
    found = conn.execute(text(
        "select * from landing.peak_invoice where import_run_id = :r %s order by due_on desc nulls last, doc_no "
        "limit :lim offset :off" % clause), params).mappings().all()
    return {"rows": [{k: _iso(v) for k, v in dict(r).items()} for r in found],
            "total": total, "limit": limit, "offset": offset}


def odoo_phone_rows(conn):
    found = conn.execute(text(
        "select t.volt_id, t.phone_e164 from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'ODOO' and t.phone_e164 is not null and t.phone_e164 <> ''")).mappings().all()
    return [dict(r) for r in found]


def _served(row, rule=None):
    r = dict(row)
    return {"doc_no": r["doc_no"], "doc_kind": r["doc_kind"], "issued_on": _iso(r["issued_on"]),
            "due_on": _iso(r["due_on"]), "status": r["status"],
            "cycle": {"n": r["cycle_n"], "of": r["cycle_of"]} if r["cycle_n"] else None,
            "product_group": r["product_group"], "amount_total": str(r["amount_total"]) if r["amount_total"] is not None else None,
            "amount_due": str(r["amount_due"]) if r["amount_due"] is not None else None,
            "amount_awaiting": str(r["amount_awaiting"] or "0.00"),
            "payment": ({"on": _iso(r["paid_on"]), "channel": r["paid_channel"],
                         "amount": str(r["paid_amount"]) if r["paid_amount"] is not None else None,
                         "receipt_no": r["receipt_no"]} if r["paid_on"] or r["receipt_no"] else None),
            "contact_code": r["contact_code"], "rule": rule or r["rule"]}


def invoices_for_book(conn):
    """The last APPLIED run's EXACT rows, plus any row of that run whose contact code
    or reference has an active link — rung 0 applied at read time."""
    run = last_run(conn, applied=True)
    if run is None:
        return {}
    as_of = (run.get("meta") or {}).get("report_as_of")
    out = {}
    exact = conn.execute(text(
        "select * from landing.peak_invoice where import_run_id = :r and verdict = 'EXACT' and customer_no is not null"),
        {"r": run["id"]}).mappings().all()
    for r in exact:
        out.setdefault(r["customer_no"], {"report_as_of": as_of, "run_id": run["id"], "invoices": []})["invoices"].append(_served(r))
    linked = conn.execute(text(
        "select p.*, l.customer_no as linked_no from landing.peak_invoice p "
        "join records.identity_link l on l.retired_at is null and "
        "(l.contact_code = upper(replace(coalesce(p.contact_code, ''), ' ', '')) "
        " or l.contact_code = upper(replace(coalesce(p.reference, ''), ' ', ''))) "
        "where p.import_run_id = :r and p.verdict <> 'EXACT'"), {"r": run["id"]}).mappings().all()
    for r in linked:
        out.setdefault(r["linked_no"], {"report_as_of": as_of, "run_id": run["id"], "invoices": []})["invoices"].append(_served(r, rule="LINK"))
    for block in out.values():
        block["invoices"].sort(key=lambda i: (i["due_on"] or "", i["doc_no"]))
    return out
```

- [ ] **Step 5: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_writer.py -v`
Expected: PASS — 9 tests. The `normalise_code` import means `confirm("vl0010239,vc0010541")` stores `VL0010239,99999000328`, which is what the `upper(replace(...))` join in `invoices_for_book` compares against.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipelines/peak_links.py backend/app/pipelines/peak_writer.py backend/tests/test_peak_writer.py
git commit -m "feat(peak): one PEAK import run with verdicts, an apply step, and a link register a person owns"
```

---

### Task 5: The run sequence — `peak_service.py`, and `runs.latest(kind=None)`

**Files:**
- Create: `backend/app/pipelines/peak_service.py`
- Modify: `backend/app/pipelines/runs.py:86` (`latest`)
- Test: `backend/tests/test_peak_service.py` (create); `backend/tests/test_pipeline_runs.py` (append one test)

**Interfaces:**
- Consumes: Tasks 2–4; `runs.start/progress/finish/fail/get`; `journey.book_customers()`; `db.configured()/connect()`.
- Produces: `peak_service.run_upload(raw, filename, uid=None) -> run view`; `runs.latest(kind=None)`. Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_service.py
"""The PEAK run sequence, once: parse → match → write, every exit through the registry."""
import pytest

from app import db
from app.pipelines import peak_service, runs
from tests.test_peak_report import _line, _report, FILENAME


@pytest.fixture(autouse=True)
def clean_runs():
    runs.reset()
    yield
    runs.reset()


def test_without_a_database_the_run_fails_honestly_and_says_why(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "failed"
    assert run["problem"]["code"] == "database_required"


def test_an_unreadable_file_fails_with_the_parsers_own_code(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: True)
    run = peak_service.run_upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 not really", "old.xls")
    assert run["state"] == "failed" and run["problem"]["code"] == "unreadable"


def test_a_run_reports_the_parsed_total_before_it_writes(monkeypatch):
    seen = []
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(peak_service, "_land", lambda uid, parsed, filename: (seen.append(uid) or {
        "run_id": 1, "invoices": 1, "matched": 1, "candidates": 0, "unmatched": 0, "rejected": 0,
        "report_as_of": "2026-09-14", "door": "upload"}))
    run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "finished" and run["total"] == 1 and run["result"]["matched"] == 1
    assert seen == [run["uid"]]


def test_latest_can_be_asked_for_one_kind():
    a = runs.start("odoo"); runs.finish(a, {})
    b = runs.start("peak-report"); runs.finish(b, {})
    assert runs.latest()["uid"] == b
    assert runs.latest(kind="odoo")["uid"] == a
    assert runs.latest(kind="nothing") is None
```

Append the last test's twin to `backend/tests/test_pipeline_runs.py` as an ADDED test (do not touch existing ones):

```python
def test_latest_filters_by_kind_and_still_defaults_to_any():
    runs.reset()
    a = runs.start("upload"); runs.finish(a, {})
    b = runs.start("odoo"); runs.finish(b, {})
    assert runs.latest()["uid"] == b
    assert runs.latest(kind="upload")["uid"] == a
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_service.py tests/test_pipeline_runs.py -v`
Expected: FAIL — module not found; `latest() got an unexpected keyword argument 'kind'`.

- [ ] **Step 3: Write the service and widen `latest`**

In `backend/app/pipelines/runs.py`, replace `def latest():` with:

```python
def latest(kind=None):
    """The newest run, of any kind or of one. `kind` is the value start() was given."""
    found = [r for r in all() if kind is None or r.get("kind") == kind]
    return found[-1] if found else None
```

(Read `all()` first: if it returns oldest-first, `[-1]` is newest; if newest-first, use `[0]`. The existing `latest` body tells you which — keep its ordering.)

```python
# backend/app/pipelines/peak_service.py
"""The PEAK report run sequence, once (the same shape as service.py for crm.lead).

Every exit goes through the registry. The indexes the ladder needs are built here,
from the book as it is served right now and from the ODOO rows in landing, so the
matcher itself stays pure.
"""
from .. import db, journey
from . import peak_links, peak_match, peak_report, peak_writer, runs

KIND = "peak-report"


class PipelineRefused(Exception):
    def __init__(self, problem):
        super().__init__(problem.get("detail") or problem.get("code"))
        self.problem = problem


def _land(uid, parsed, filename):
    if not db.configured():
        raise PipelineRefused({"code": "database_required",
                               "detail": "The PEAK report lands in the landing schema; set DATABASE_URL"})
    conn = db.connect()
    try:
        with conn.begin():
            book = peak_match.build_book_index(journey.book_customers())
            odoo = peak_match.build_odoo_index(peak_writer.odoo_phone_rows(conn))
            links = peak_links.load(conn)
            verdicts = peak_match.match(parsed["invoices"], book, odoo, links)
            return peak_writer.write(conn, parsed, verdicts, door="upload", filename=filename,
                                     on_progress=lambda **kw: runs.progress(uid, **kw))
    finally:
        conn.close()


def run_upload(raw, filename, uid=None):
    uid = uid or runs.start(KIND)
    try:
        parsed = peak_report.parse(raw, filename)
        runs.progress(uid, read=len(parsed["lines"]), total=len(parsed["invoices"]))
        result = _land(uid, parsed, filename)
    except peak_report.ReportError as exc:
        runs.fail(uid, {"code": exc.code, "detail": exc.detail, "detail_th": exc.detail_th})
    except PipelineRefused as exc:
        runs.fail(uid, exc.problem)
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        runs.fail(uid, {"code": "pipeline_failed", "detail": "%s: %s" % (exc.__class__.__name__, exc)})
    else:
        runs.finish(uid, result)
    return runs.get(uid)
```

If `peak_report._table` raises `ReportError("unreadable", …)` for the OLE case (Task 2 does), the second test passes as written. If the csv decoder raises `imports.UploadRefused` on garbage bytes instead, add `except imports_domain.UploadRefused as exc: runs.fail(uid, {"code": "unreadable", "detail": exc.message, "detail_th": exc.message_th})` with `from .. import imports as imports_domain`.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_service.py tests/test_pipeline_runs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/peak_service.py backend/app/pipelines/runs.py backend/tests/test_peak_service.py backend/tests/test_pipeline_runs.py
git commit -m "feat(peak): the report run sequence, and a registry that can be asked for one kind of run"
```

---

### Task 6: The book reads PEAK facts — `book_source` and `main.reload_book()`

**Files:**
- Modify: `backend/app/book_source.py:24-26` (`BLOCK_DEFAULTS`), `:100-125` (`_from_landing`)
- Modify: `backend/app/main.py:80-82` (add `reload_book()` beneath the three globals)
- Test: `backend/tests/test_peak_book.py` (create)

**Interfaces:**
- Consumes: `peak_writer.invoices_for_book(conn)` (Task 4).
- Produces: every customer record from the landing path carries `"peak": None | {"report_as_of", "run_id", "invoices": [...]}`; the book's `Customer` fixtures expose it as `customer.sheet["peak"]` (book.py already stores the whole record on `fixture.sheet`); `main.reload_book()` rebuilds `CUSTOMERS`, `BY_CUSTOMER`, `BY_CONTRACT`. Consumed by Tasks 7, 8, 9, 10, 11.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_book.py
"""PEAK facts reach the domain through the one seam the sheet already uses."""
import pytest
from sqlalchemy import text

from app import book_source, landing, migrate, main
from app.pipelines import peak_writer
from tests.test_peak_writer import _parsed, _inv, EXACT


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    yield pg_conn
    pg_conn.execute(text("delete from records.identity_link"))


def _sheet_customer(conn, customer_no="28005096535"):
    run = landing.start_run(conn, "SHEET")
    landing.write_customer(conn, run, "SHEET", {
        "volt_id": "%s_Manop_มานพ ทดสอบ_IPW" % customer_no, "customer_no": customer_no, "name_th": "มานพ ทดสอบ",
        "epc": "IPW", "product": "LEASE", "source_refs": []})
    landing.finish_run(conn, run, "OK")


def test_an_applied_run_puts_a_peak_block_on_the_customer_and_an_unapplied_one_does_not(schema):
    _sheet_customer(schema)
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535", cycle={"n": 14, "of": 48})), [EXACT])
    rec = next(c for c in book_source._from_landing(schema)["customers"] if c["customer_no"] == "28005096535")
    assert rec["peak"] is None
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    rec = next(c for c in book_source._from_landing(schema)["customers"] if c["customer_no"] == "28005096535")
    assert rec["peak"]["report_as_of"] == "2026-09-14"
    assert rec["peak"]["invoices"][0]["cycle"] == {"n": 14, "of": 48}


def test_the_fixture_path_carries_the_key_as_none_so_no_caller_has_to_guard():
    rec = book_source.load()["customers"][0]
    assert "peak" in rec and rec["peak"] is None


def test_reload_book_rebinds_the_three_globals_in_place():
    before = main.CUSTOMERS
    main.reload_book()
    assert main.CUSTOMERS is not before
    assert set(main.BY_CUSTOMER) == {c.uid for c in main.CUSTOMERS}
    assert all(main.BY_CONTRACT[k.uid][0] is c for c in main.CUSTOMERS for k in c.contracts)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_book.py -v`
Expected: FAIL — `KeyError: 'peak'`; `AttributeError: module 'app.main' has no attribute 'reload_book'`.

- [ ] **Step 3: Add the block and the reload**

`backend/app/book_source.py` — in `BLOCK_DEFAULTS` add `"peak": None`, and in `_from_landing` after `blocks = landing.blocks_for(...)`:

```python
    # Feedback Round 1 / WP1 (vault note 10 §3): the last APPLIED PEAK run, keyed by
    # customer_no — the same seam as the sheet's blocks, so the domain never learns a
    # second data path. An unapplied run is invisible here on purpose.
    from .pipelines import peak_writer
    peak_blocks = peak_writer.invoices_for_book(conn)
```

and inside the per-customer loop, after the `for block, empty in BLOCK_DEFAULTS.items():` line:

```python
        record["peak"] = peak_blocks.get(str(customer.get("customer_no") or ""))
```

For the fixture path, in `_with_captured_on` (which every load path already passes through) add, after the `source.setdefault(...)` line:

```python
    for rec in payload.get("customers") or []:
        rec.setdefault("peak", None)
```

`backend/app/main.py`, directly under line 82:

```python
def reload_book():
    """Rebuild the served book from book_source (Feedback Round 1 / WP1 Task 6).

    Called after a PEAK report is applied so the new facts are served without a
    restart. Per-session journey and cases state seeded from the OLD book is NOT
    touched here — a tester's work is theirs; the current session re-seeds its PEAK
    invoices in journey.reseed_peak, and other sessions see the facts at their next
    reset. Rebinding by assignment is what conftest already does, so anything that
    reads the book at call time (journey.book_customers) sees the new one.
    """
    global CUSTOMERS, BY_CUSTOMER, BY_CONTRACT
    CUSTOMERS = seed()
    BY_CUSTOMER = {c.uid: c for c in CUSTOMERS}
    BY_CONTRACT = {k.uid: (c, k) for c in CUSTOMERS for k in c.contracts}
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_book.py tests/test_book_source.py -v`
Expected: PASS (if `tests/test_book_source.py` is named differently, run the file that covers `book_source`: `grep -l book_source backend/tests/*.py`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/book_source.py backend/app/main.py backend/tests/test_peak_book.py
git commit -m "feat(book): the applied PEAK report rides on the customer as its peak block, and the book can be rebuilt in place"
```

---

### Task 7: Invoices and receipts from PEAK facts — `journey._seed_peak_invoices`, `reseed_peak`

**Files:**
- Modify: `backend/app/journey.py:797-830` (`_seed_migrated_invoices`), add two functions beside it
- Modify: `backend/app/config.py:173` (add `peak_report_allocates: bool = True`)
- Test: `backend/tests/test_peak_book.py` (extend)

**Interfaces:**
- Consumes: `customer.sheet["peak"]` (Task 6); `make_invoice`, `make_receipt`; `settings.peak_report_allocates` (design F3).
- Produces: invoice records with `source == "PEAK_REPORT"`, `peak_number`, `peak_state == "APPROVED_IN_PEAK"`, `month_index`, `outstanding`, `contract_resolved`; receipt records with `source == "PEAK_REPORT"`, `ref`, `is_allocated`; `journey.reseed_peak(state, bd)`. Consumed by Tasks 8–11.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_peak_book.py`)

```python
import datetime

from app import journey
from app.config import settings


def _with_peak(invoices, report_as_of="2026-09-14"):
    """Put a peak block on the first LEASE customer of the fixture book, for this test only
    (fresh_app_state re-seeds main.CUSTOMERS per test)."""
    customer = next(c for c in journey.book_customers() if c.contracts and c.contracts[0].product == "LEASE")
    customer.sheet = dict(customer.sheet, peak={"report_as_of": report_as_of, "run_id": 1, "invoices": invoices})
    journey.reset()
    return customer, journey.for_current()


PAID = {"doc_no": "IVT-1", "doc_kind": "IVT", "issued_on": "2026-06-05", "due_on": "2026-06-12", "status": "PAID",
        "cycle": {"n": 3, "of": 48}, "product_group": "Solar Leasing", "amount_total": "8399.00", "amount_due": "8399.00",
        "amount_awaiting": "0.00", "payment": {"on": "2026-06-10", "channel": "Beam", "amount": "8399.00",
                                               "receipt_no": "RE-1"}, "contact_code": "VC1", "rule": "CUSTOMER_NO"}
LATE = dict(PAID, doc_no="IVT-2", due_on="2026-07-12", status="OVERDUE", cycle={"n": 4, "of": 48},
            amount_awaiting="8399.00", payment=None)
DRAFT = dict(PAID, doc_no="IVT-3", status="DRAFT", payment=None)


def _mine(state, customer):
    uids = {k.uid for k in customer.contracts}
    return ([i for i in state.invoices.values() if i["contract_uid"] in uids],
            [r for r in state.receipts.values() if r["contract_uid"] in uids])


def test_a_customer_with_peak_facts_gets_peak_invoices_and_no_sheet_invented_ones():
    customer, state = _with_peak([PAID, LATE, DRAFT])
    invoices, receipts = _mine(state, customer)
    assert {i["peak_number"] for i in invoices} == {"IVT-1", "IVT-2"}, "a DRAFT is not an issued invoice"
    assert all(i["source"] == "PEAK_REPORT" and i["scenario"] == "PEAK" for i in invoices)
    late = next(i for i in invoices if i["peak_number"] == "IVT-2")
    assert late["state"] == "OVERDUE" and late["outstanding"] == "8399.00" and late["month_index"] == 4
    assert late["peak_state"] == "APPROVED_IN_PEAK" and "PEAK" in late["peak_state_note_th"]
    assert len(receipts) == 1 and receipts[0]["ref"] == "RE-1" and receipts[0]["source"] == "PEAK_REPORT"
    assert receipts[0]["invoice_uid"] == next(i["uid"] for i in invoices if i["peak_number"] == "IVT-1")


def test_a_peak_receipt_is_allocated_by_ruling_f3_and_not_when_the_switch_is_off(monkeypatch):
    customer, state = _with_peak([PAID])
    assert _mine(state, customer)[1][0]["is_allocated"] is True
    monkeypatch.setattr(settings, "peak_report_allocates", False)
    customer, state = _with_peak([PAID])
    rcp = _mine(state, customer)[1][0]
    assert rcp["is_allocated"] is False and rcp["pending_decision"] == "OD-02"


def test_an_awaiting_invoice_past_its_due_date_reads_overdue_by_the_business_date():
    customer, state = _with_peak([dict(LATE, status="AWAITING", due_on="2020-01-01")])
    assert _mine(state, customer)[0][0]["state"] == "OVERDUE"


def test_reseed_replaces_peak_rows_and_keeps_everything_else():
    customer, state = _with_peak([PAID])
    before = len(state.invoices)
    customer.sheet = dict(customer.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [PAID, LATE]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    invoices, _ = _mine(state, customer)
    assert {i["peak_number"] for i in invoices} == {"IVT-1", "IVT-2"}
    assert len(state.invoices) == before + 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_book.py -v`
Expected: FAIL — the PEAK invoices are not seeded (`peak_number` set is empty), `reseed_peak` missing.

- [ ] **Step 3: Seed from PEAK facts**

`backend/app/config.py`, beside `late_payment_daily_rate` in `class Settings`:

```python
    # Feedback Round 1 / WP1, design F3: a PEAK receipt naming its invoice is PEAK's own
    # allocation. True records it as allocated (PEAK-sourced receipts only); False
    # leaves it under OD-02 like a slip. The engine's instalment lines are NOT
    # re-allocated by this switch — that is allocation-engine work, priced separately.
    peak_report_allocates: bool = True
```

`backend/app/journey.py` — at the top of the per-customer loop in `_seed_migrated_invoices`, right after the `if customer.data_source != SHEET or not customer.contracts: continue` line:

```python
        peak = (getattr(customer, "sheet", {}) or {}).get("peak")
        if peak and peak.get("invoices"):
            # Feedback Round 1 / WP1: PEAK facts exist for this customer, so nothing is
            # walked back from the sheet's cells — a real invoice beats an inferred one.
            _seed_peak_invoices(state, customer, peak, bd)
            continue
```

and beside `_sheet_peak_state`:

```python
PEAK_STATE = {"PAID": "PAID", "OVERDUE": "OVERDUE", "AWAITING": "SENT"}


def _peak_contract_for(customer, inv):
    """One contract → it. Several → the product group decides (Cash → CASH, Solar
    Leasing → LEASE); otherwise the first, marked unresolved rather than guessed silently."""
    contracts = list(customer.contracts)
    if len(contracts) == 1:
        return contracts[0], True
    group = (inv.get("product_group") or "").lower()
    want = "CASH" if "cash" in group else ("LEASE" if "leas" in group else None)
    for k in contracts:
        if want and k.product == want:
            return k, True
    return contracts[0], False


def _seed_peak_invoices(state, customer, peak, bd):
    note_th = "จากรายงานใบแจ้งหนี้ PEAK ณ %s" % (peak.get("report_as_of") or "—")
    for row in peak["invoices"]:
        if row["status"] == "DRAFT":
            continue                                   # not an issued invoice
        contract, resolved = _peak_contract_for(customer, row)
        entity = contract.entity or ("SPV" if contract.product == "LEASE" else "EPC")
        due_on = _date_or(row.get("due_on"), bd)
        state_code = PEAK_STATE[row["status"]]
        if row["status"] == "AWAITING" and due_on < bd:
            state_code = "OVERDUE"
        amount = row.get("amount_due") or row.get("amount_total") or "0"
        inv = make_invoice(state, contract.uid, entity,
                           "INSTALMENT" if contract.product == "LEASE" else "HANDOVER_BALANCE",
                           amount, due_on, state_code, scenario="PEAK",
                           issued_on=_date_or(row.get("issued_on"), due_on))
        inv["source"] = "PEAK_REPORT"
        inv["peak_number"] = row["doc_no"]
        inv["peak_state"] = "APPROVED_IN_PEAK"
        inv["peak_state_note_th"] = note_th
        inv["outstanding"] = str(Decimal(row.get("amount_awaiting") or "0").quantize(Decimal("0.01")))
        inv["month_index"] = (row.get("cycle") or {}).get("n")
        inv["contract_resolved"] = resolved
        inv["link_sent"] = None                      # PEAK does not say; nothing is invented
        pay = row.get("payment")
        if pay and pay.get("amount") and pay.get("on"):
            rcp = make_receipt(state, contract.uid, entity, pay["amount"], pay["on"],
                               invoice_uid=inv["uid"], matched="MATCHED")
            rcp["source"] = "PEAK_REPORT"
            rcp["ref"] = pay.get("receipt_no")
            rcp["channel"] = pay.get("channel")
            if settings.peak_report_allocates:      # design F3
                rcp["is_allocated"], rcp["exception_raised"], rcp["pending_decision"] = True, False, None


def _date_or(raw, fallback):
    if not raw:
        return fallback
    y, m, d = (int(p) for p in str(raw)[:10].split("-"))
    return date(y, m, d)


def reseed_peak(state, bd):
    """After a PEAK report is applied in THIS session: drop every PEAK-sourced invoice
    and receipt and seed again from the book as it is now served. Everything a
    person recorded (slips, contacts, PTPs) is untouched."""
    for uid in [u for u, i in state.invoices.items() if i.get("source") == "PEAK_REPORT"]:
        del state.invoices[uid]
    for uid in [u for u, r in state.receipts.items() if r.get("source") == "PEAK_REPORT"]:
        del state.receipts[uid]
    for customer in book_customers():
        peak = (getattr(customer, "sheet", {}) or {}).get("peak")
        if peak and peak.get("invoices") and customer.contracts:
            _seed_peak_invoices(state, customer, peak, bd)
```

Check `journey.py`'s imports already include `date`, `Decimal` and `settings` (they are used elsewhere in the file); add any that are missing.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_book.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && python -m pytest --continue-on-collection-errors`
Expected: the Task 0 baseline plus the new tests. **Paste the count.** No fixture customer carries a `peak` block, so no existing test can move; if one does, stop and report it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/journey.py backend/app/config.py backend/tests/test_peak_book.py
git commit -m "feat(journey): invoices and receipts seeded from PEAK facts where they exist, allocation by ruling F3"
```

---

### Task 8: The router — `/v1/pipelines/peak-report/*`

**Files:**
- Create: `backend/app/routers/peak_pipeline.py`
- Modify: `backend/app/main.py:1571` (include the router beside `pipelines_router`)
- Test: `backend/tests/test_peak_router.py` (create)

**Interfaces:**
- Consumes: Tasks 4–7; `routers.pipelines._manager_only`, `routers.pipelines._body`, `routers.pipelines._require_db`; `audit.describe`.
- Produces:

| Endpoint | Role | Does |
|---|---|---|
| `POST /v1/pipelines/peak-report:run` | Manager | raw body + `X-Volt-Filename`; runs synchronously; returns the run view |
| `POST /v1/pipelines/peak-report:start` | Manager | 202 + uid; runs on a thread |
| `GET /v1/pipelines/peak-report/runs/{uid}` | any | the registry view |
| `GET /v1/pipelines/peak-report/last-run` | any | `{staged, applied, watch}` |
| `GET /v1/pipelines/peak-report/landing-runs/{id}/rows?verdict=&limit=&offset=` | any | paged rows |
| `POST /v1/pipelines/peak-report/landing-runs/{id}:apply` | Manager | body `{"allow_older": bool}`; applies, reloads the book, re-seeds this session, re-checks every case's status (Task 11); audit act `PEAK_REPORT_APPLIED` |
| `GET /v1/pipelines/peak-report/links` | any | active links (`?include_retired=true` for history) |
| `POST /v1/pipelines/peak-report/links` | Manager | `{contact_code, customer_no, reason, contract_uid?}`; audit `PEAK_LINK_CONFIRMED` |
| `POST /v1/pipelines/peak-report/links/{uid}:retire` | Manager | audit `PEAK_LINK_RETIRED` |

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_peak_router.py
"""The PEAK report endpoints: Manager-only writes, honest about the database, and
the same (200, 503) latitude test_pipeline_router.py already takes."""
from fastapi.testclient import TestClient

from app.main import app
from tests.test_peak_report import _line, _report, FILENAME

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def test_an_officer_may_not_run_or_apply_or_link():
    assert client.post("/v1/pipelines/peak-report:run", content=b"x", headers=OFFICER).status_code == 403
    assert client.post("/v1/pipelines/peak-report/landing-runs/1:apply", json={}, headers=OFFICER).status_code == 403
    assert client.post("/v1/pipelines/peak-report/links", json={"contact_code": "VC1", "customer_no": "1"},
                       headers=OFFICER).status_code == 403


def test_an_empty_body_is_a_validation_problem():
    r = client.post("/v1/pipelines/peak-report:run", content=b"", headers={**MANAGER, "X-Volt-Filename": "x.xlsx"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "required"


def test_a_report_runs_and_the_answer_names_its_counts_or_the_missing_database():
    r = client.post("/v1/pipelines/peak-report:run", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": FILENAME, "Content-Type": "application/octet-stream"})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body["state"] == "finished" and body["result"]["invoices"] == 1
    else:
        assert r.json()["code"] == "database_required"


def test_starting_answers_at_once_with_a_uid_to_watch():
    r = client.post("/v1/pipelines/peak-report:start", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": FILENAME, "Content-Type": "application/octet-stream"})
    assert r.status_code == 202 and r.json()["uid"]
    assert client.get("/v1/pipelines/peak-report/runs/%s" % r.json()["uid"]).status_code == 200


def test_an_unknown_run_is_a_404():
    assert client.get("/v1/pipelines/peak-report/runs/run-nope").status_code == 404


def test_a_link_needs_a_code_and_a_customer():
    r = client.post("/v1/pipelines/peak-report/links", json={"contact_code": "", "customer_no": ""}, headers=MANAGER)
    assert r.status_code in (422, 503)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_peak_router.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the router**

```python
# backend/app/routers/peak_pipeline.py
"""The PEAK invoice report door — vault note 10 §3 WP1.

Same shape as routers/pipelines.py (raw body, X-Volt-Filename, Manager-only writes,
202 + uid to watch) so the officer meets one intake desk with three source cards.
"""
import re
import threading
from pathlib import Path

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse

from .. import audit, cases as cases_domain, db, errors, journey
from ..pipelines import peak_links, peak_service, peak_writer, runs
from .pipelines import _body, _manager_only, _require_db

router = APIRouter()
PREFIX = "/v1/pipelines/peak-report"


def _filename(header):
    return re.sub(r"[^\w.\- ]", "", Path(header or "").name)[:120] or None


def _require_body(raw):
    if not raw:
        raise errors.validation_failed([{"pointer": "/file", "code": "required",
                                         "message": "The request body is empty.",
                                         "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])


@router.post(PREFIX + ":run")
async def run_report(request: Request, x_volt_role: str = Header(default="OFFICER"),
                     x_volt_filename: str = Header(default=None)):
    _manager_only(x_volt_role)
    raw = await _body(request)
    _require_body(raw)
    run = peak_service.run_upload(raw, _filename(x_volt_filename))
    if run["state"] == "failed" and (run.get("problem") or {}).get("code") == "database_required":
        _require_db()
    return run


@router.post(PREFIX + ":start", status_code=202)
async def start_report(request: Request, x_volt_role: str = Header(default="OFFICER"),
                       x_volt_filename: str = Header(default=None)):
    _manager_only(x_volt_role)
    raw = await _body(request)
    _require_body(raw)
    uid = runs.start(peak_service.KIND)
    threading.Thread(target=peak_service.run_upload, args=(raw, _filename(x_volt_filename), uid),
                     daemon=True).start()
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get(PREFIX + "/runs/{uid}")
def get_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("pipeline run")
    return run


@router.get(PREFIX + "/last-run")
def last_run():
    watch = runs.latest(kind=peak_service.KIND)
    if not db.configured():
        return {"staged": None, "applied": None, "watch": watch}
    conn = db.connect()
    try:
        return {"staged": peak_writer.last_run(conn, applied=False),
                "applied": peak_writer.last_run(conn, applied=True), "watch": watch}
    finally:
        conn.close()


@router.get(PREFIX + "/landing-runs/{run_id}/rows")
def run_rows(run_id: int, verdict: str = Query(default=None),
             limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    if verdict not in (None, "", "EXACT", "CANDIDATE", "UNMATCHED", "REJECTED"):
        raise errors.validation_failed([{"pointer": "/verdict", "code": "invalid",
                                         "message": "verdict is EXACT, CANDIDATE, UNMATCHED or REJECTED",
                                         "message_th": "verdict ต้องเป็น EXACT, CANDIDATE, UNMATCHED หรือ REJECTED"}])
    _require_db()
    conn = db.connect()
    try:
        return peak_writer.rows(conn, run_id, verdict=verdict or None, limit=limit, offset=offset)
    finally:
        conn.close()


def _refused(exc):
    status = 404 if exc.code == "not_found" else 409
    return errors.Problem(code=exc.code, status=status, title="PEAK report refused",
                          detail=exc.detail, message_th=exc.detail_th, error_id="DEBT-PEAK-%04d" % status)


def _after_apply():
    """The three things an apply changes in THIS process, in order: the served book,
    this session's PEAK invoices, and every case's system payment status (Task 11)."""
    from .. import main
    main.reload_book()
    journey.reseed_peak(journey.for_current(), main.BUSINESS_DATE)
    cases_domain.follow_system_for_all()


@router.post(PREFIX + "/landing-runs/{run_id}:apply")
def apply_run(run_id: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
              x_volt_officer: str = Header(default=None)):
    _manager_only(x_volt_role)
    _require_db()
    body = body or {}
    conn = db.connect()
    try:
        with conn.begin():
            try:
                run = peak_writer.apply_run(conn, run_id, by=x_volt_officer or "manager",
                                            allow_older=bool(body.get("allow_older")))
            except peak_writer.WriterRefused as exc:
                raise _refused(exc)
    finally:
        conn.close()
    _after_apply()
    meta = run.get("meta") or {}
    audit.describe(act="PEAK_REPORT_APPLIED", subject=("import_run", str(run_id)),
                   detail={"report_as_of": meta.get("report_as_of"), "matched": meta.get("matched"),
                           "candidates": meta.get("candidates"), "unmatched": meta.get("unmatched"),
                           "allow_older": bool(body.get("allow_older"))})
    return {"run": run, "note_th": "ใช้รายงานนี้แล้ว — เซสชันนี้เห็นข้อมูลใหม่ทันที ผู้ทดสอบคนอื่นเห็นเมื่อรีเซ็ตเซสชัน"}


@router.get(PREFIX + "/links")
def links(include_retired: bool = Query(default=False)):
    _require_db()
    conn = db.connect()
    try:
        return {"links": peak_links.list_links(conn, include_retired=include_retired)}
    finally:
        conn.close()


@router.post(PREFIX + "/links", status_code=201)
def confirm_link(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None)):
    _manager_only(x_volt_role)
    code, no = (body.get("contact_code") or "").strip(), str(body.get("customer_no") or "").strip()
    problems = []
    if not code:
        problems.append({"pointer": "/contact_code", "code": "required", "message": "contact_code is required",
                         "message_th": "ต้องระบุรหัสผู้ติดต่อ PEAK"})
    if not no:
        problems.append({"pointer": "/customer_no", "code": "required", "message": "customer_no is required",
                         "message_th": "ต้องระบุเลขลูกค้า"})
    if problems:
        raise errors.validation_failed(problems)
    _require_db()
    if not any(c.customer_no == no for c in journey.book_customers()):
        raise errors.not_found("customer %s" % no)
    conn = db.connect()
    try:
        with conn.begin():
            link = peak_links.confirm(conn, code, no, by=x_volt_officer or "manager", reason=body.get("reason"),
                                      contract_uid=body.get("contract_uid"))
    finally:
        conn.close()
    _after_apply()
    audit.describe(act="PEAK_LINK_CONFIRMED", subject=("customer", "sheet-%s" % no),
                   detail={"contact_code": link["contact_code"], "reason": body.get("reason")})
    return {"link": link}


@router.post(PREFIX + "/links/{uid}:retire")
def retire_link(uid: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
                x_volt_officer: str = Header(default=None)):
    _manager_only(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        with conn.begin():
            link = peak_links.retire(conn, uid, by=x_volt_officer or "manager")
    finally:
        conn.close()
    if link is None:
        raise errors.not_found("active link %s" % uid)
    _after_apply()
    audit.describe(act="PEAK_LINK_RETIRED", subject=("customer", "sheet-%s" % link["customer_no"]),
                   detail={"contact_code": link["contact_code"], "reason": (body or {}).get("reason")})
    return {"link": link}
```

In `backend/app/main.py`, beside the `pipelines_router` import add `from .routers.peak_pipeline import router as peak_pipeline_router`, and after line 1571 add `app.include_router(peak_pipeline_router)`.

`cases_domain.follow_system_for_all` does not exist until Task 11. Until then, add it to `cases.py` as a stub that returns `[]` with the comment `# Task 11 fills this in`, so Task 8 runs green — and Task 11 replaces the stub.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_peak_router.py tests/test_pipeline_router.py -v`
Expected: PASS.

- [ ] **Step 5: Check the audit middleware logs the new acts**

Run: `cd backend && python -c "from app import audit; print(audit.is_logged('POST', '/v1/pipelines/peak-report/landing-runs/{run_id}:apply'), audit.is_logged('POST', '/v1/pipelines/peak-report/links'))"`
Expected: `True True`. If `False`, read `audit.is_logged`'s rule (it decides by verb and route template) and add the two templates the way the existing POST routes are covered — never by special-casing in the router.

- [ ] **Step 6: Run the e2e harness**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED; e2e count unchanged (routes were added, none changed). **Paste the counts.**

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/peak_pipeline.py backend/app/main.py backend/app/cases.py backend/tests/test_peak_router.py
git commit -m "feat(api): the PEAK report door — run, watch, apply, and the links a person confirms"
```

---

### Task 9: The overview says which source each cycle is drawn from — `payment_summary` overlay

**Files:**
- Modify: `backend/app/payment_summary.py` (`for_contract`, `build`)
- Modify: `backend/app/routers/today.py:720-721` (pass `peak_cycles`)
- Test: `backend/tests/test_payment_summary.py` (append — additions only)

**Interfaces:**
- Consumes: invoice records with `source == "PEAK_REPORT"` and `month_index` (Task 7).
- Produces: `payment_summary.for_contract(contract, business_date, overdue_amount, month_cells=None, peak_cycles=None)` where `peak_cycles = {n: {"status", "paid", "outstanding", "doc_no"}}`; each cycle gains `source: "PEAK" | "SHEET_DERIVED"`; each contract gains `source`, `peak: {"invoices": int, "report_as_of": str} | None`, `unplaced_peak_invoices: int`; `build()` sets `indicative` False only when every due cycle is PEAK-sourced, and picks the provenance sentence to match. `payment_summary.peak_cycles_for(contract_uid, jstate) -> (peak_cycles, unplaced_count, report_as_of)` is the helper the router calls. Consumed by Task 18 (frontend).

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_payment_summary.py`)

```python
from app import payment_summary


def test_a_peak_cycle_overlays_the_engines_status_and_says_so():
    import datetime
    from app import journey
    customer = next(c for c in journey.book_customers() if c.contracts and c.contracts[0].product == "LEASE")
    contract = customer.contracts[0]
    peak = {2: {"status": "PAID", "paid": "8399.00", "outstanding": "0.00", "doc_no": "IVT-2"},
            3: {"status": "OVERDUE", "paid": "0.00", "outstanding": "8399.00", "doc_no": "IVT-3"}}
    out = payment_summary.for_contract(contract, datetime.date(2026, 10, 23), "0.00", peak_cycles=peak)
    by_n = {c["n"]: c for c in out["cycles"]}
    assert by_n[2]["status"] == "PAID" and by_n[2]["source"] == "PEAK" and by_n[2]["doc_no"] == "IVT-2"
    assert by_n[3]["status"] == "OVERDUE" and by_n[3]["source"] == "PEAK"
    assert by_n[1]["source"] == "SHEET_DERIVED"
    assert out["source"] == "PEAK" and out["peak"]["invoices"] == 2


def test_without_peak_the_contract_is_sheet_derived_as_before():
    import datetime
    from app import journey
    customer = next(c for c in journey.book_customers() if c.contracts)
    out = payment_summary.for_contract(customer.contracts[0], datetime.date(2026, 10, 23), "0.00")
    assert out["source"] == "SHEET_DERIVED" and out["peak"] is None
    assert all(c["source"] == "SHEET_DERIVED" for c in out["cycles"])


def test_the_summary_is_indicative_unless_every_due_cycle_is_peaks():
    import datetime
    from app import journey
    customer = next(c for c in journey.book_customers() if c.contracts and c.contracts[0].product == "LEASE")
    contract = customer.contracts[0]
    bd = datetime.date(2026, 10, 23)
    partial = payment_summary.build([payment_summary.for_contract(contract, bd, "0.00",
                                                                 peak_cycles={1: {"status": "PAID", "paid": "1", "outstanding": "0", "doc_no": "x"}})], bd)
    assert partial["indicative"] is True
    due = [c["n"] for c in payment_summary.for_contract(contract, bd, "0.00")["cycles"] if c["due_date"] <= str(bd)]
    every = {n: {"status": "PAID", "paid": "1", "outstanding": "0", "doc_no": "x"} for n in due}
    full = payment_summary.build([payment_summary.for_contract(contract, bd, "0.00", peak_cycles=every)], bd)
    assert full["indicative"] is False and "PEAK" in full["provenance_th"]


def test_peak_cycles_for_reads_this_sessions_peak_invoices():
    from app import journey
    from tests.test_peak_book import _with_peak, PAID, LATE
    customer, state = _with_peak([PAID, LATE, dict(LATE, doc_no="IVT-9", cycle=None)])
    cycles, unplaced, as_of = payment_summary.peak_cycles_for(customer.contracts[0].uid, state)
    assert set(cycles) == {3, 4} and cycles[4]["status"] == "OVERDUE" and cycles[3]["doc_no"] == "IVT-1"
    assert unplaced == 1 and as_of == "2026-09-14"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_summary.py -v`
Expected: FAIL — unexpected keyword `peak_cycles`, missing `source`.

- [ ] **Step 3: Add the overlay**

In `backend/app/payment_summary.py`:

```python
PROVENANCE_PEAK_TH = "สถานะแต่ละงวดมาจากรายงานใบแจ้งหนี้ PEAK (จ่ายแล้ว / เกินกำหนด / รอชำระ) ตามเลขงวด M n/N บนใบแจ้งหนี้"
PROVENANCE_PEAK_EN = "each cycle's status comes from the PEAK invoice report, by the M n/N cycle mark on the invoice"
PROVENANCE_MIXED_TH = PROVENANCE_TH + " · งวดที่มีใบแจ้งหนี้ PEAK ใช้สถานะจาก PEAK"
PROVENANCE_MIXED_EN = PROVENANCE_EN + " · cycles with a PEAK invoice take PEAK's status"

PEAK_CYCLE_STATUS = {"PAID": "PAID", "OVERDUE": "OVERDUE", "SENT": "UPCOMING", "ISSUED": "UPCOMING",
                     "PARTIALLY_PAID": "OVERDUE"}


def peak_cycles_for(contract_uid, jstate):
    """This session's PEAK invoices for one contract, keyed by cycle. An invoice with no
    cycle mark is counted as unplaced, never dropped onto a slot."""
    cycles, unplaced, as_of = {}, 0, None
    for inv in jstate.invoices.values():
        if inv["contract_uid"] != contract_uid or inv.get("source") != "PEAK_REPORT":
            continue
        as_of = as_of or (inv.get("peak_state_note_th") or "").rsplit(" ", 1)[-1]
        n = inv.get("month_index")
        if not n:
            unplaced += 1
            continue
        outstanding = Decimal(inv.get("outstanding") or inv["amount"])
        cycles[n] = {"status": PEAK_CYCLE_STATUS.get(inv["state"], "UPCOMING"),
                     "paid": _money(Decimal(inv["amount"]) - outstanding), "outstanding": _money(outstanding),
                     "doc_no": inv.get("peak_number")}
    return cycles, unplaced, (as_of if as_of and as_of != "—" else None)
```

In `for_contract`, add the parameter `peak_cycles=None`, and inside the `for n, line in enumerate(lines, start=1):` loop replace the `cycles.append({...})` with:

```python
        cycle = {
            "n": n, "kind": _kind(contract.product, n), "due_date": str(line.due_date),
            "amount": _money(line.total_amount), "paid": _money(paid), "outstanding": _money(outstanding),
            "status": _status(line, business_date), "partly_paid": paid > 0 and outstanding > 0,
            "source": "SHEET_DERIVED", "doc_no": None,
        }
        hit = (peak_cycles or {}).get(n)
        if hit:
            # A real invoice beats an inferred cycle: PEAK's status, paid and outstanding
            # replace the engine's for this slot, and the slot says so.
            cycle.update(status=hit["status"], paid=hit["paid"], outstanding=hit["outstanding"],
                         partly_paid=Decimal(hit["paid"]) > 0 and Decimal(hit["outstanding"]) > 0,
                         source="PEAK", doc_no=hit.get("doc_no"))
        cycles.append(cycle)
```

and in the returned dict add:

```python
        "source": "PEAK" if any(c["source"] == "PEAK" for c in cycles) else "SHEET_DERIVED",
        "peak": ({"invoices": len(peak_cycles), "report_as_of": None} if peak_cycles else None),
        "unplaced_peak_invoices": 0,
```

(The router fills `report_as_of` and `unplaced_peak_invoices` from `peak_cycles_for`'s other two values — see Step 4.)

In `build`, replace the fixed `"indicative": True` and the two provenance lines with:

```python
    due_cycles = [c for e in entries for c in e["cycles"] if c["due_date"] <= str(business_date)]
    all_peak = bool(due_cycles) and all(c["source"] == "PEAK" for c in due_cycles)
    any_peak = any(c["source"] == "PEAK" for e in entries for c in e["cycles"])
    ...
        "indicative": not all_peak,
        "provenance_th": PROVENANCE_PEAK_TH if all_peak else (PROVENANCE_MIXED_TH if any_peak else PROVENANCE_TH),
        "provenance_en": PROVENANCE_PEAK_EN if all_peak else (PROVENANCE_MIXED_EN if any_peak else PROVENANCE_EN),
```

- [ ] **Step 4: Pass the cycles from the router**

`backend/app/routers/today.py`, at the `summaries.append(payment_summary.for_contract(...))` call (line ~720):

```python
        peak_cycles, unplaced, peak_as_of = payment_summary.peak_cycles_for(k.uid, journey.for_current())
        entry = payment_summary.for_contract(k, main_module().BUSINESS_DATE, block.cumulative_arrears,
                                             month_cells=k_months, peak_cycles=peak_cycles or None)
        if entry["peak"]:
            entry["peak"]["report_as_of"] = peak_as_of
        entry["unplaced_peak_invoices"] = unplaced
        summaries.append(entry)
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `cd backend && python -m pytest tests/test_payment_summary.py -v && python -m pytest --continue-on-collection-errors`
Expected: PASS; suite at baseline + additions. `test_payment_summary.py`'s existing tests assert `indicative is True` on fixture customers — still true, because no fixture customer has PEAK cycles. **Paste the count.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/payment_summary.py backend/app/routers/today.py backend/tests/test_payment_summary.py
git commit -m "feat(overview): a cycle with a PEAK invoice takes PEAK's status and says so; the picture is indicative only where it is inferred"
```

---

### Task 10: `payment_position` — the block, its provenance, served on three rows

**Files:**
- Create: `backend/app/payment_position.py`
- Modify: `backend/app/config.py` (add `payment_position_stale_days: int = 30`)
- Modify: `backend/app/routers/journey.py:237` (work item), `backend/app/routers/today.py:914` (invoices payload), `:379-410` (work-book row projection and `meta.columns`), `:763` (case detail)
- Test: `backend/tests/test_payment_position.py` (extend the existing file)

**Interfaces:**
- Consumes: `journey` invoices and receipts (Task 7's `source` values included); `book_source.build()["source"]["captured_on"]`; `customer.sheet["peak"]["report_as_of"]`.
- Produces: `payment_position.build(customer, jstate, business_date) -> dict` with keys `paid_count, open_count, total_count, oldest_unpaid, last_money_in, source, as_of, as_of_days, stale, note_th` — `source` in `SHEET | SLIP | PEAK_DOC | PEAK_REPORT`. Served as `payment_position` on `GET /v1/today` items, `GET /v1/workbook` rows (+ `meta.columns`), `GET /v1/cases/by-customer/{uid}` (`work_item.payment_position`) and `…/invoices`. Consumed by Tasks 13, 14, 18, 19.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_payment_position.py`)

```python
import datetime

import pytest
from fastapi.testclient import TestClient

from app import journey, payment_position
from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def jstate():
    journey.reset()
    yield journey.for_current()
    journey.reset()


def _customer_with(jstate, invoices, receipts=()):
    customer = next(c for c in journey.book_customers() if c.contracts)
    contract_uid = customer.contracts[0].uid
    for uid in [u for u, i in jstate.invoices.items() if i["contract_uid"] == contract_uid]:
        del jstate.invoices[uid]
    for uid in [u for u, r in jstate.receipts.items() if r["contract_uid"] == contract_uid]:
        del jstate.receipts[uid]
    for amount, due, state, peak_number in invoices:
        inv = journey.make_invoice(jstate, contract_uid, "SPV", "INSTALMENT", amount, due, state)
        inv["peak_number"] = peak_number
    for amount, on, source, ref in receipts:
        rcp = journey.make_receipt(jstate, contract_uid, "SPV", amount, on)
        rcp["source"], rcp["ref"] = source, ref
    return customer


def test_it_counts_paid_and_open_and_names_the_oldest_unpaid(jstate):
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 4, 12), "PAID", "IVT-20260400091"),
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", "IVT-20260500090"),
        ("8399.00", datetime.date(2026, 6, 18), "OVERDUE", "IVT-20260600090")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert (block["paid_count"], block["open_count"], block["total_count"]) == (1, 2, 3)
    assert block["oldest_unpaid"]["peak_number"] == "IVT-20260500090"
    assert block["oldest_unpaid"]["due_date"] == "2026-05-12"
    assert isinstance(block["oldest_unpaid"]["outstanding"], str)


def test_with_no_receipt_the_source_is_the_sheet_and_the_capture_date_or_unknown(jstate):
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "OVERDUE", None)])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "SHEET" and block["last_money_in"] is None
    assert block["as_of"] is None and block["stale"] is None and "ไม่ทราบ" in block["note_th"]


def test_the_newest_receipt_moves_the_source_and_the_as_of(jstate):
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "PAID", None)],
                              [("38257.45", "2026-07-16", "PEAK_REPORT", "RE-20260700272"),
                               ("8399.00", "2026-03-02", "SLIP", "slip-0001")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "PEAK_REPORT" and block["as_of"] == "2026-07-16"
    assert block["last_money_in"] == {"amount": "38257.45", "on": "2026-07-16", "source": "PEAK_REPORT", "ref": "RE-20260700272"}
    assert block["as_of_days"] == 57 and block["stale"] is True


def test_a_peak_customer_with_no_receipt_is_as_of_the_report(jstate):
    from tests.test_peak_book import _with_peak, LATE
    customer, state = _with_peak([LATE])
    block = payment_position.build(customer, state, datetime.date(2026, 9, 21))
    assert block["source"] == "PEAK_REPORT" and block["as_of"] == "2026-09-14" and block["open_count"] == 1


def test_the_four_surfaces_serve_the_position():
    item = client.get("/v1/today").json()["items"][0]
    assert item["payment_position"]["source"] in ("SHEET", "SLIP", "PEAK_DOC", "PEAK_REPORT")
    uid = item["customer"]["uid"]
    assert "payment_position" in client.get("/v1/cases/by-customer/%s/invoices" % uid).json()
    assert "payment_position" in client.get("/v1/cases/by-customer/%s" % uid).json()["work_item"]
    book = client.get("/v1/workbook").json()
    assert "payment_position" in book["rows"][0] and "payment_position" in book["meta"]["columns"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: FAIL — `ModuleNotFoundError: app.payment_position`.

- [ ] **Step 3: Write the module and the config key**

`backend/app/config.py`, in `class Settings` beside `peak_report_allocates`:

```python
    # Plan 2026-09-11 §1.3, carried into Feedback Round 1: a chosen default, not a ruled one.
    payment_position_stale_days: int = 30
```

```python
# backend/app/payment_position.py
"""The payment position — plan 2026-09-11 §1.1, built in Feedback Round 1 (WP1/WP3).

Four questions in one server-owned block: did they pay, how much is left, when did
money last come in, and WHO SAYS SO. The manager's own words: "each case shows how
many invoices are paid and how many unpaid remain".

Every figure is produced here, once, as a string (api.js:1-4). When the as-of date
is unknowable the block refuses — as_of, as_of_days and stale are None and note_th
says so — rather than printing today's date as if it knew.
"""
from datetime import date
from decimal import Decimal

from . import book_source
from .config import settings

OPEN_STATES = ("ISSUED", "SENT", "PARTIALLY_PAID", "OVERDUE")
SETTLED_STATES = ("PAID",)
SOURCES = ("SHEET", "SLIP", "PEAK_DOC", "PEAK_REPORT")

NOTE_UNKNOWN_TH = ("ไม่ทราบว่าข้อมูลการชำระนี้เป็นข้อมูล ณ วันใด — ชีตที่นำเข้าไม่ได้บันทึกวันที่ดึงข้อมูล "
                   "จึงบอกไม่ได้ว่าเก่าแค่ไหน")
NOTE_SHEET_TH = "ข้อมูลการชำระมาจากชีต ณ วันที่ %s"
NOTE_RECEIPT_TH = {
    "SLIP": "ข้อมูลล่าสุดมาจากสลิปที่เจ้าหน้าที่ยืนยัน เมื่อ %s",
    "PEAK_DOC": "ข้อมูลล่าสุดมาจากเอกสาร PEAK ที่อัปโหลด เมื่อ %s",
    "PEAK_REPORT": "ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ %s",
}
NOTE_STALE_TH = " · เก่ากว่า %d วัน ควรตรวจสอบกับ PEAK"


def _sheet_captured_on():
    return (book_source.load().get("source") or {}).get("captured_on")


def _money(raw):
    return str(Decimal(str(raw)).quantize(Decimal("0.01")))


def _date(raw):
    y, m, d = (int(p) for p in str(raw)[:10].split("-"))
    return date(y, m, d)


def _mine(customer, rows):
    uids = {k.uid for k in customer.contracts}
    return [r for r in rows.values() if r["contract_uid"] in uids]


def _oldest_unpaid(invoices):
    open_rows = [i for i in invoices if i["state"] in OPEN_STATES]
    if not open_rows:
        return None
    oldest = min(open_rows, key=lambda i: (i["due_date"] is None, i["due_date"] or "", i["uid"]))
    outstanding = oldest.get("outstanding")
    if outstanding in (None, ""):
        outstanding = oldest["amount"]
    return {"uid": oldest["uid"], "peak_number": oldest.get("peak_number"),
            "due_date": oldest["due_date"], "outstanding": _money(outstanding)}


def _last_money_in(receipts):
    dated = [r for r in receipts if r.get("received_on")]
    if not dated:
        return None
    newest = max(dated, key=lambda r: (str(r["received_on"]), r["uid"]))
    source = newest.get("source") or "SLIP"
    return {"amount": _money(newest["amount"]), "on": str(newest["received_on"])[:10],
            "source": source if source in SOURCES else "SLIP", "ref": newest.get("ref") or newest["uid"]}


def build(customer, jstate, business_date):
    invoices = _mine(customer, jstate.invoices)
    receipts = _mine(customer, jstate.receipts)
    last_in = _last_money_in(receipts)
    peak = (getattr(customer, "sheet", {}) or {}).get("peak") or {}
    if last_in is not None:
        source, as_of = last_in["source"], last_in["on"]
        note = NOTE_RECEIPT_TH.get(source, NOTE_RECEIPT_TH["SLIP"]) % as_of
    elif any(i.get("source") == "PEAK_REPORT" for i in invoices) and peak.get("report_as_of"):
        source, as_of = "PEAK_REPORT", peak["report_as_of"]
        note = NOTE_RECEIPT_TH["PEAK_REPORT"] % as_of
    else:
        source, as_of = "SHEET", _sheet_captured_on()
        note = NOTE_SHEET_TH % as_of if as_of else NOTE_UNKNOWN_TH
    if as_of:
        as_of_days = (business_date - _date(as_of)).days
        stale = as_of_days > settings.payment_position_stale_days
        if stale:
            note += NOTE_STALE_TH % settings.payment_position_stale_days
    else:
        as_of_days, stale = None, None
    return {
        "paid_count": sum(1 for i in invoices if i["state"] in SETTLED_STATES),
        "open_count": sum(1 for i in invoices if i["state"] in OPEN_STATES),
        "total_count": len(invoices),
        "oldest_unpaid": _oldest_unpaid(invoices),
        "last_money_in": last_in,
        "source": source, "as_of": as_of, "as_of_days": as_of_days, "stale": stale, "note_th": note,
    }
```

- [ ] **Step 4: Serve it at the four sites**

`backend/app/routers/journey.py`, beside line 237's `"money_position": money_position(customer, total),`:

```python
        # Plan 2026-09-11 §1.4 / Feedback Round 1: the position rides beside the money.
        "payment_position": payment_position.build(customer, journey.for_current(), business_date),
```

(`business_date` is the `_work_item` parameter; add `from .. import payment_position`.) The case page's `work_item` comes from `_work_item`, so `GET /v1/cases/by-customer/{uid}` is covered by this one line — verify with the test, do not add it twice.

`backend/app/routers/today.py:914`, in the invoices payload: `"payment_position": payment_position.build(customer, jstate, main_module().BUSINESS_DATE),`.

`backend/app/routers/today.py` work-book projection (around line 379–410, where `money = r.get("money_position") or {}` is read): the row is projected from a work item, so add `"payment_position": r.get("payment_position")` to the projected dict and append `"payment_position"` to the `meta.columns` list at that site. The CLOSED-row path (`test_round4.py:775` pins that exactly seven keys differ) builds its own rows: add the same key there, from the same `_work_item`, so the septet stays seven.

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `cd backend && python -m pytest tests/test_payment_position.py tests/test_round4.py -v && python -m pytest --continue-on-collection-errors`
Expected: PASS; `test_round4.py`'s seven-key assertion unchanged. **Paste the count.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/payment_position.py backend/app/config.py backend/app/routers/journey.py backend/app/routers/today.py backend/tests/test_payment_position.py
git commit -m "feat(payments): the payment position — paid and open counts, oldest unpaid, last money in, and who says so"
```

---

### Task 11: The case's system payment status follows PEAK (design F2) — `cases._payment_status`, `follow_system_for_all`

**Files:**
- Modify: `backend/app/cases.py:577-590` (`_payment_status`), `:follow_system_payment_status` (extract `_follow`), add `follow_system_for_all`, add `peak_report_drives_status` reading
- Modify: `backend/app/config.py` (add `peak_report_drives_status: bool = True`)
- Test: `backend/tests/test_payment_status_adjust.py` (append — additions only)

**Interfaces:**
- Consumes: `customer.sheet["peak"]` (Task 6), `settings.business_date`.
- Produces: `cases._payment_status(customer)` reads PEAK when present; `cases.follow_system_for_all() -> list[case]` re-checks every case in the current session and writes the same `PAYMENT_STATUS_SET` event and audit detail the contract path does. Consumed by Task 8's `_after_apply`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_payment_status_adjust.py`)

```python
def test_a_linked_customers_status_is_peaks_not_the_sheets(monkeypatch):
    from app import cases, journey
    from app.config import settings
    from tests.test_peak_book import _with_peak, PAID, LATE
    # A LEASE customer the sheet marks LATE, whose PEAK invoices are all paid.
    customer, _ = _with_peak([PAID])
    assert cases._payment_status(customer) == "CURRENT"
    customer, _ = _with_peak([PAID, LATE])
    assert cases._payment_status(customer) == "LATE"
    monkeypatch.setattr(settings, "peak_report_drives_status", False)
    assert cases._payment_status(customer) == cases._payment_status_from_contracts(customer)


def test_npl_and_closed_still_win_over_peak():
    from app import cases
    from tests.test_peak_book import _with_peak, PAID
    customer, _ = _with_peak([PAID])
    cases._set_contract_fields(customer.contracts[0], status="NON_PERFORMING")
    assert cases._payment_status(customer) == "NPL"


def test_follow_system_for_all_writes_one_event_per_case_that_moved():
    from app import cases
    from tests.test_peak_book import _with_peak, PAID
    state = cases.for_current()
    customer, _ = _with_peak([PAID])
    case = state.cases[customer.uid]
    case["payment_status_system"], case["payment_status"] = "LATE", "LATE"
    moved = cases.follow_system_for_all()
    assert case in moved and case["payment_status"] == "CURRENT"
    ev = [e for e in state.events if e["kind"] == "PAYMENT_STATUS_SET" and e["case_uid"] == case["uid"]][-1]
    assert ev["by"] == "SYSTEM" and ev["code"] == "CURRENT" and ev["from"] == "LATE"
    assert cases.follow_system_for_all() == [], "nothing moved the second time"
```

If `cases._set_contract_fields` needs more arguments than `(contract, status=...)`, read its signature and call it the way `set_npl`'s path does; the intent is a contract in `NON_PERFORMING`.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_status_adjust.py -v`
Expected: FAIL — `_payment_status` still reads the sheet; `follow_system_for_all` returns `[]` (Task 8's stub).

- [ ] **Step 3: Implement**

`backend/app/config.py`, beside `peak_report_allocates`:

```python
    # Feedback Round 1, design F2: for a customer linked to PEAK, the system's own
    # payment status is worked out from the PEAK invoices. This partly supersedes
    # Requirements Amendment v2.6 §3.6 a second time (the first was 2026-09-14's
    # person-may-change rule); recorded here, at cases._payment_status, and in the
    # commit that introduced it.
    peak_report_drives_status: bool = True
```

`backend/app/cases.py` — rename the existing `_payment_status` to `_payment_status_from_contracts` (unchanged body) and add:

```python
def _peak_says(customer):
    """LATE / CURRENT from the PEAK invoices, or None when this customer has none."""
    peak = (getattr(customer, "sheet", {}) or {}).get("peak") or {}
    rows = [r for r in peak.get("invoices") or [] if r.get("status") != "DRAFT"]
    if not rows:
        return None
    bd = str(settings.business_date)
    for r in rows:
        if r["status"] == "OVERDUE" or (r["status"] == "AWAITING" and (r.get("due_on") or "9999") < bd):
            return "LATE"
    return "CURRENT"


def _payment_status(customer):
    """Design F2: the contract statuses that mean NPL, CLOSED or NOT_INSTALLED still
    win (a person or the ladder set them); between LATE and CURRENT, PEAK's invoices
    decide when the customer is linked and the switch is on."""
    from_contracts = _payment_status_from_contracts(customer)
    if from_contracts in ("NPL", "CLOSED", "NOT_INSTALLED") or not settings.peak_report_drives_status:
        return from_contracts
    peak = _peak_says(customer)
    return peak if peak is not None else from_contracts
```

Then extract the body of `follow_system_payment_status` after `customer = found[0]` into `_follow(state, case, customer)` (everything from `_payment_status_fields(case)` to the `return case`), have `follow_system_payment_status` call it, and add:

```python
def follow_system_for_all():
    """After a PEAK report is applied (Task 8): every case in this session is re-checked
    the same way a contract change re-checks one. Returns the cases that moved."""
    state = for_current()
    moved = []
    for case in list(state.cases.values()):
        customer = _customer_for(case)
        if customer is None:
            continue
        if _follow(state, case, customer) is not None:
            moved.append(case)
    return moved
```

where `_customer_for(case)` is `journey.customer_by_uid(case["customer_uid"])` (import `journey` lazily inside the function if `cases.py` does not already import it, to keep the import cycle as it is). Remove Task 8's stub.

- [ ] **Step 4: Run the tests, then the suite**

Run: `cd backend && python -m pytest tests/test_payment_status_adjust.py tests/test_cases.py -v && python -m pytest --continue-on-collection-errors`
Expected: PASS at baseline + additions. No fixture customer has a `peak` block, so every existing status stays what it was. **Paste the count.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/cases.py backend/app/config.py backend/tests/test_payment_status_adjust.py
git commit -m "feat(case): a customer linked to PEAK takes LATE or CURRENT from PEAK's invoices (design F2, supersedes v2.6 §3.6 in part)"
```

---

### Task 12: The PEAK source card on Data sources — `api.js`, `PeakReportCard.jsx`

**Files:**
- Modify: `frontend/src/api.js:336-340` (add the bindings beside `crmLeadSchedule`)
- Create: `frontend/src/components/PeakReportCard.jsx`
- Create: `frontend/src/components/PeakReportCard.test.jsx`
- Modify: `frontend/src/screens/DataSourcesMigration.jsx` (mount the card after the crm.lead intake desk)
- Modify: `frontend/src/i18n-admin.js` (`peak.*` keys, EN and TH)
- Modify: `frontend/src/journey.css` (tokens only; `journey.test.js` enforces it)

**Interfaces:**
- Consumes: Task 8's endpoints; `DropZone`, `RunProgress`, `Problem`, `fromError`, `SearchSelect`.
- Produces: `api.peakReportStart(file)`, `api.peakReportRun(uid)`, `api.peakReportLastRun()`, `api.peakReportRows(runId, params)`, `api.peakReportApply(runId, body)`, `api.peakLinks(params)`, `api.peakLinkConfirm(body)`, `api.peakLinkRetire(uid, body)`; `<PeakReportCard />` (no props; reads the role store for the Manager gate).

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/PeakReportCard.test.jsx
// The PEAK report source card: a run you can watch, a receipt with the three
// verdict counts, and the two lists a person acts on — candidates and unmatched.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from './role.jsx'
import { PeakReportCard } from './PeakReportCard.jsx'

vi.mock('../api.js', () => ({
  api: {
    peakReportStart: vi.fn(), peakReportRun: vi.fn(), peakReportLastRun: vi.fn(),
    peakReportRows: vi.fn(), peakReportApply: vi.fn(), peakLinks: vi.fn(),
    peakLinkConfirm: vi.fn(), peakLinkRetire: vi.fn(), workbook: vi.fn(),
  },
}))

const STAGED = { id: 7, source_system: 'PEAK', status: 'OK', finished_at: '2026-09-15T09:00:00Z',
                 meta: { report_as_of: '2026-09-14', door: 'upload', matched: 2824, candidates: 610, unmatched: 4204, rejected: [] },
                 row_counts: { read: 7999, landed: 7638, rejected: 1 } }
const APPLIED = { ...STAGED, id: 6, meta: { ...STAGED.meta, report_as_of: '2026-08-31', applied: { by: 'settasak', at: '2026-09-01T02:00:00Z' } } }
const ROW = { doc_no: 'IVT-20260700089', contact_code: 'VL0010239,VC0010687', customer_name: 'Somchai Tamdee',
              status: 'OVERDUE', due_on: '2026-07-18', amount_awaiting: '13060.45', verdict: 'CANDIDATE',
              candidates: [{ customer_no: '28005096535', rule: 'COMPOSITE:VOLT_ID', code: 'VC0010687' }] }

const Card = () => <MemoryRouter><PeakReportCard /></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  setRole('MANAGER'); setOfficer('settasak')
  api.peakReportLastRun.mockResolvedValue({ staged: STAGED, applied: APPLIED, watch: null })
  api.peakReportRows.mockResolvedValue({ rows: [ROW], total: 1, limit: 100, offset: 0 })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.workbook.mockResolvedValue({ rows: [{ customer: { uid: 'sheet-28005096535', customer_no: '28005096535', display_name: 'มานพ ทดสอบ' } }] })
})

describe('PeakReportCard', () => {
  it('prints the applied report date and the staged receipt with its three verdict counts', async () => {
    renderIn('th', <Card />)
    expect(await screen.findByTestId('peak-applied')).toHaveTextContent('31/08/2026')
    const receipt = screen.getByTestId('peak-receipt')
    expect(within(receipt).getByTestId('peak-matched')).toHaveTextContent('2,824')
    expect(within(receipt).getByTestId('peak-candidates')).toHaveTextContent('610')
    expect(within(receipt).getByTestId('peak-unmatched')).toHaveTextContent('4,204')
  })

  it('offers apply to a Manager and refuses it to an Officer in words', async () => {
    renderIn('th', <Card />)
    expect(await screen.findByRole('button', { name: /ใช้รายงานนี้/ })).toBeEnabled()
    setRole('OFFICER')
    renderIn('th', <Card />)
    expect((await screen.findAllByTestId('peak-manager-only'))[0]).toBeInTheDocument()
  })

  it('lists a candidate row with the rule that produced it and confirms the link with a reason', async () => {
    api.peakLinkConfirm.mockResolvedValue({ link: { uid: 1, contact_code: 'VL0010239,VC0010687', customer_no: '28005096535' } })
    renderIn('th', <Card />)
    const row = await screen.findByTestId('peak-row-IVT-20260700089')
    expect(row).toHaveTextContent('COMPOSITE:VOLT_ID')
    fireEvent.click(within(row).getByRole('button', { name: /ผูก 28005096535/ }))
    fireEvent.change(within(row).getByLabelText('เหตุผล'), { target: { value: 'เปลี่ยนแพ็กเกจ' } })
    fireEvent.click(within(row).getByRole('button', { name: 'ยืนยัน' }))
    await waitFor(() => expect(api.peakLinkConfirm).toHaveBeenCalledWith({
      contact_code: 'VL0010239,VC0010687', customer_no: '28005096535', reason: 'เปลี่ยนแพ็กเกจ' }))
  })

  it('an unmatched row links through a customer search, never a free-typed number', async () => {
    api.peakReportRows.mockResolvedValue({ rows: [{ ...ROW, verdict: 'UNMATCHED', candidates: [] }], total: 1, limit: 100, offset: 0 })
    renderIn('th', <Card />)
    const row = await screen.findByTestId('peak-row-IVT-20260700089')
    fireEvent.change(within(row).getByRole('searchbox'), { target: { value: 'มานพ' } })
    await waitFor(() => expect(api.workbook).toHaveBeenCalledWith(expect.objectContaining({ q: 'มานพ' })))
    fireEvent.click(await within(row).findByRole('option', { name: /มานพ ทดสอบ/ }))
    expect(within(row).getByRole('button', { name: 'ยืนยัน' })).toBeDisabled()   // reason first
  })

  it('renders the empty state, not a crash, when the API has no PEAK run yet', async () => {
    api.peakReportLastRun.mockResolvedValue({ staged: null, applied: null, watch: null })
    renderIn('th', <Card />)
    expect(await screen.findByTestId('peak-empty')).toBeInTheDocument()
  })

  it('shows a refusal verbatim when apply is rejected', async () => {
    api.peakReportApply.mockRejectedValue(Object.assign(new Error('x'), { problem: {
      code: 'report_older_than_applied', title: 'PEAK report refused', message_th: 'รายงานนี้เก่ากว่ารายงานที่ใช้อยู่' } }))
    renderIn('th', <Card />)
    fireEvent.click(await screen.findByRole('button', { name: /ใช้รายงานนี้/ }))
    expect(await screen.findByText(/รายงานนี้เก่ากว่า/)).toBeInTheDocument()
    expect(screen.getByLabelText(/ใช้รายงานเก่ากว่า/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/PeakReportCard.test.jsx`
Expected: FAIL — cannot resolve `./PeakReportCard.jsx`.

- [ ] **Step 3: Add the API bindings**

`frontend/src/api.js`, after `crmLeadSchedule`:

```js
  // Feedback Round 1 / WP1 — the PEAK invoice report door (routers/peak_pipeline.py).
  peakReportStart: (file) => postRaw('/v1/pipelines/peak-report:start', file),
  peakReportRun: (uid) => get(`/v1/pipelines/peak-report/runs/${uid}`),
  peakReportLastRun: () => get('/v1/pipelines/peak-report/last-run'),
  peakReportRows: (runId, params) => get(`/v1/pipelines/peak-report/landing-runs/${runId}/rows`, params),
  peakReportApply: (runId, body) => post(`/v1/pipelines/peak-report/landing-runs/${runId}:apply`, body || {}),
  peakLinks: (params) => get('/v1/pipelines/peak-report/links', params),
  peakLinkConfirm: (body) => post('/v1/pipelines/peak-report/links', body),
  peakLinkRetire: (uid, body) => post(`/v1/pipelines/peak-report/links/${uid}:retire`, body || {}),
```

- [ ] **Step 4: Write the card**

```jsx
// frontend/src/components/PeakReportCard.jsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../prefs.jsx'
import { useRole } from './role.jsx'
import DropZone from './DropZone.jsx'
import RunProgress from './RunProgress.jsx'
import { Problem } from './Problem.jsx'
import { fromError } from '../problem.js'
import { format } from './Money.jsx'
import { formatDate } from './NextAction.jsx'

// The third source card on the intake desk (vault note 10 §3 WP1). Same custody
// shape as the crm.lead card: a door, a run you can watch, a permanent receipt —
// and then the two lists a person acts on. Every number is the run's own.
const VERDICTS = ['CANDIDATE', 'UNMATCHED']
const MANAGER = ['MANAGER', 'OWNER']

function num(n) { return n === null || n === undefined ? '—' : Number(n).toLocaleString('en-US') }

export function PeakReportCard() {
  const t = useT()
  const { role } = useRole()
  const isManager = MANAGER.includes(role)
  const fileRef = useRef(null)
  const [last, setLast] = useState(null)        // {staged, applied, watch}
  const [run, setRun] = useState(null)          // the registry view being watched
  const [rows, setRows] = useState({ CANDIDATE: null, UNMATCHED: null })
  const [problem, setProblem] = useState(null)
  const [allowOlder, setAllowOlder] = useState(false)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    if (typeof api.peakReportLastRun !== 'function') return
    try {
      const d = await api.peakReportLastRun()
      setLast(d)
      const staged = d?.staged
      if (staged) {
        const pages = await Promise.all(VERDICTS.map((v) => api.peakReportRows(staged.id, { verdict: v, limit: 100 })))
        setRows({ CANDIDATE: pages[0], UNMATCHED: pages[1] })
      } else {
        setRows({ CANDIDATE: null, UNMATCHED: null })
      }
    } catch (e) { setProblem(fromError(e)) }
  }, [])

  useEffect(() => { reload() }, [reload])

  async function onFile(file) {
    if (!file || typeof api.peakReportStart !== 'function') return
    setProblem(null)
    try {
      let view = await api.peakReportStart(file)
      setRun(view)
      while (view && view.state === 'running') {
        await new Promise((r) => setTimeout(r, 750))
        view = await api.peakReportRun(view.uid)
        setRun(view)
      }
      await reload()
    } catch (e) { setProblem(fromError(e)) }
  }

  async function apply() {
    if (!last?.staged || busy) return
    setBusy(true); setProblem(null)
    try {
      await api.peakReportApply(last.staged.id, { allow_older: allowOlder })
      await reload()
    } catch (e) { setProblem(fromError(e)) } finally { setBusy(false) }
  }

  const staged = last?.staged
  const applied = last?.applied
  const meta = staged?.meta || {}

  return (
    <section className="card ad-section peak-card" aria-labelledby="peak-title" data-testid="peak-report-card">
      <h2 className="ad-h2" id="peak-title">{t('peak.title')}</h2>
      <p className="ad-quiet">{t('peak.sub')}</p>

      <p className="peak-card__applied" data-testid="peak-applied">
        {applied
          ? t('peak.appliedOn', { date: formatDate(applied.meta?.report_as_of) || '—', by: applied.meta?.applied?.by || '—' })
          : t('peak.appliedNone')}
      </p>

      {isManager ? (
        <DropZone inputRef={fileRef} label={t('peak.dropLabel')} hint={t('peak.dropHint')} accept=".xlsx,.csv" onFile={onFile} />
      ) : (
        <p className="ad-quiet" data-testid="peak-manager-only">{t('peak.managerOnly')}</p>
      )}

      <div className="manifest" data-testid="peak-manifest">
        {run && <RunProgress run={run} />}
        {!staged && !run && <p className="manifest__empty" data-testid="peak-empty">{t('peak.receiptEmpty')}</p>}
        {staged && (
          <dl className="manifest__rows" data-testid="peak-receipt">
            <div className="manifest__row"><dt>{t('peak.reportAsOf')}</dt><dd>{formatDate(meta.report_as_of) || '—'}</dd></div>
            <div className="manifest__row"><dt>{t('peak.invoices')}</dt><dd>{num(staged.row_counts?.landed)}</dd></div>
            <div className="manifest__row"><dt>{t('peak.matched')}</dt><dd data-testid="peak-matched">{num(meta.matched)}</dd></div>
            <div className="manifest__row"><dt>{t('peak.candidates')}</dt><dd data-testid="peak-candidates">{num(meta.candidates)}</dd></div>
            <div className="manifest__row"><dt>{t('peak.unmatched')}</dt><dd data-testid="peak-unmatched">{num(meta.unmatched)}</dd></div>
            <div className="manifest__row"><dt>{t('peak.rejected')}</dt><dd>{num(staged.row_counts?.rejected)}</dd></div>
          </dl>
        )}
        {staged && !meta.applied && isManager && (
          <div className="peak-card__apply">
            <button type="button" className="btn btn--primary" disabled={busy} onClick={apply}>{t('peak.apply')}</button>
            <label className="ad-check">
              <input type="checkbox" checked={allowOlder} onChange={(e) => setAllowOlder(e.target.checked)} />
              {' '}{t('peak.allowOlder')}
            </label>
            <p className="ad-quiet">{t('peak.applyNote')}</p>
          </div>
        )}
        {problem && <Problem problem={problem} />}
      </div>

      {VERDICTS.map((v) => (
        <PeakRows key={v} verdict={v} page={rows[v]} isManager={isManager} t={t} onChanged={reload} />
      ))}
    </section>
  )
}

function PeakRows({ verdict, page, isManager, t, onChanged }) {
  if (!page) return null
  return (
    <div className="peak-rows" data-testid={`peak-rows-${verdict}`}>
      <h3 className="ad-h3">{t(`peak.list.${verdict}`)} <span className="ad-quiet">{t('peak.listCount', { n: page.total })}</span></h3>
      {page.rows.length === 0 && <p className="ad-quiet">{t('peak.listEmpty')}</p>}
      <ul className="peak-rows__list">
        {page.rows.map((r) => <PeakRow key={r.doc_no} row={r} isManager={isManager} t={t} onChanged={onChanged} />)}
      </ul>
    </div>
  )
}

function PeakRow({ row, isManager, t, onChanged }) {
  const [pick, setPick] = useState(null)          // {customer_no, display_name}
  const [reason, setReason] = useState('')
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!q.trim() || typeof api.workbook !== 'function') { setHits([]); return }
    let alive = true
    api.workbook({ q: q.trim(), limit: 8 }).then((d) => { if (alive) setHits(d?.rows || []) }).catch(() => setHits([]))
    return () => { alive = false }
  }, [q])

  async function confirm() {
    if (!pick || !reason.trim() || busy) return
    setBusy(true); setProblem(null)
    try {
      await api.peakLinkConfirm({ contact_code: row.contact_code, customer_no: pick.customer_no, reason: reason.trim() })
      onChanged && onChanged()
    } catch (e) { setProblem(fromError(e)) } finally { setBusy(false) }
  }

  return (
    <li className="peak-row" data-testid={`peak-row-${row.doc_no}`}>
      <div className="peak-row__facts">
        <code className="td-mono">{row.doc_no}</code>
        <span>{row.customer_name || '—'}</span>
        <code className="td-mono">{row.contact_code || '—'}</code>
        <span className={`chip chip--${row.status === 'PAID' ? 'current' : 'held'}`}>{t(`peak.status.${row.status}`)}</span>
        <span className="td-mono">{format(row.amount_awaiting)}</span>
        <span className="td-quiet">{formatDate(row.due_on) || row.due_on || '—'}</span>
      </div>
      {row.verdict === 'CANDIDATE' && (
        <ul className="peak-row__cands">
          {(row.candidates || []).map((c) => (
            <li key={c.customer_no + c.rule}>
              <code className="td-mono">{c.rule}</code>{' '}
              {isManager && (
                <button type="button" className="btn btn--sm" onClick={() => setPick({ customer_no: c.customer_no })}>
                  {t('peak.linkTo', { no: c.customer_no })}
                </button>
              )}
              {!isManager && <span className="td-mono">{c.customer_no}</span>}
            </li>
          ))}
        </ul>
      )}
      {row.verdict === 'UNMATCHED' && isManager && (
        <div className="peak-row__search">
          <input type="search" className="fb__search" value={q} placeholder={t('peak.searchCustomer')}
                 aria-label={t('peak.searchCustomer')} onChange={(e) => setQ(e.target.value)} />
          {hits.length > 0 && (
            <ul role="listbox" className="ss__list">
              {hits.map((h) => (
                <li key={h.customer.uid} role="option" aria-selected={pick?.customer_no === h.customer.customer_no}>
                  <button type="button" className="ss__opt" onClick={() => { setPick({ customer_no: h.customer.customer_no, display_name: h.customer.display_name }); setHits([]) }}>
                    {h.customer.display_name} <code className="td-mono">{h.customer.customer_no}</code>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {pick && (
        <div className="peak-row__confirm">
          <span>{t('peak.linkPicked', { no: pick.customer_no })}</span>
          <label>
            <span>{t('peak.reason')}</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="btn btn--primary btn--sm" disabled={!reason.trim() || busy} onClick={confirm}>{t('peak.confirm')}</button>
          <button type="button" className="btn btn--sm" onClick={() => { setPick(null); setReason('') }}>{t('peak.cancel')}</button>
        </div>
      )}
      {problem && <Problem problem={problem} />}
    </li>
  )
}
```

Read `DropZone.jsx`'s props before wiring it: if its file callback is named differently from `onFile` (the crm.lead card passes it from the screen), use the screen's own prop names verbatim. `useRole` is exported from `components/role.jsx` — confirm the hook's name there; the identity menu uses it.

Add to `frontend/src/i18n-admin.js`, both tables (EN, then TH):

```js
  'peak.title': 'PEAK invoice report', 'peak.sub': 'Drop the PEAK "รายงานใบแจ้งหนี้" export. The run matches every invoice to a customer by a named rule and applies nothing until you say so.',
  'peak.appliedOn': 'Applied report: as of {date} · by {by}', 'peak.appliedNone': 'No PEAK report has been applied yet',
  'peak.dropLabel': 'Choose the PEAK export', 'peak.dropHint': '.xlsx or .csv · up to 25 MB',
  'peak.managerOnly': 'Only a Manager or the Owner runs and applies a PEAK report', 'peak.receiptEmpty': 'No run yet — the receipt appears here',
  'peak.reportAsOf': 'Report as of', 'peak.invoices': 'Invoices', 'peak.matched': 'Matched by an exact rule', 'peak.candidates': 'Need a person to confirm',
  'peak.unmatched': 'Not matched', 'peak.rejected': 'Rows refused', 'peak.apply': 'Apply this report', 'peak.allowOlder': 'Apply even if older than the applied report',
  'peak.applyNote': 'Apply serves the exact matches at once. Confirmed links serve their invoices at once too, without a re-run.',
  'peak.list.CANDIDATE': 'To confirm', 'peak.list.UNMATCHED': 'Not matched', 'peak.listCount': '{n} invoices', 'peak.listEmpty': 'Nothing here',
  'peak.linkTo': 'Link to {no}', 'peak.linkPicked': 'Link to customer {no}', 'peak.searchCustomer': 'Search a customer by name or number',
  'peak.reason': 'Reason', 'peak.confirm': 'Confirm', 'peak.cancel': 'Cancel',
  'peak.status.PAID': 'paid', 'peak.status.OVERDUE': 'overdue', 'peak.status.AWAITING': 'awaiting', 'peak.status.DRAFT': 'draft',
```

```js
  'peak.title': 'รายงานใบแจ้งหนี้ PEAK', 'peak.sub': 'วางไฟล์ส่งออก "รายงานใบแจ้งหนี้" จาก PEAK ระบบจะจับคู่ใบแจ้งหนี้กับลูกค้าตามกฎที่ระบุชื่อ และไม่ใช้ข้อมูลจนกว่าคุณจะสั่ง',
  'peak.appliedOn': 'รายงานที่ใช้อยู่: ณ {date} · โดย {by}', 'peak.appliedNone': 'ยังไม่มีรายงาน PEAK ที่ใช้อยู่',
  'peak.dropLabel': 'เลือกไฟล์ส่งออกจาก PEAK', 'peak.dropHint': '.xlsx หรือ .csv · ไม่เกิน 25 MB',
  'peak.managerOnly': 'เฉพาะผู้จัดการหรือเจ้าของระบบที่นำเข้าและใช้รายงาน PEAK ได้', 'peak.receiptEmpty': 'ยังไม่มีรอบนำเข้า — ใบรับจะแสดงที่นี่',
  'peak.reportAsOf': 'รายงาน ณ วันที่', 'peak.invoices': 'ใบแจ้งหนี้', 'peak.matched': 'จับคู่ได้ตามกฎแน่นอน', 'peak.candidates': 'รอคนยืนยัน',
  'peak.unmatched': 'จับคู่ไม่ได้', 'peak.rejected': 'แถวที่ปฏิเสธ', 'peak.apply': 'ใช้รายงานนี้', 'peak.allowOlder': 'ใช้รายงานเก่ากว่ารายงานที่ใช้อยู่',
  'peak.applyNote': 'เมื่อใช้รายงาน ใบที่จับคู่ได้แน่นอนจะแสดงทันที การผูกที่ยืนยันแล้วก็แสดงทันทีโดยไม่ต้องนำเข้าใหม่',
  'peak.list.CANDIDATE': 'รอยืนยัน', 'peak.list.UNMATCHED': 'จับคู่ไม่ได้', 'peak.listCount': '{n} ใบ', 'peak.listEmpty': 'ไม่มีรายการ',
  'peak.linkTo': 'ผูก {no}', 'peak.linkPicked': 'ผูกกับลูกค้า {no}', 'peak.searchCustomer': 'ค้นหาลูกค้าด้วยชื่อหรือเลขลูกค้า',
  'peak.reason': 'เหตุผล', 'peak.confirm': 'ยืนยัน', 'peak.cancel': 'ยกเลิก',
  'peak.status.PAID': 'จ่ายแล้ว', 'peak.status.OVERDUE': 'เกินกำหนด', 'peak.status.AWAITING': 'รอชำระ', 'peak.status.DRAFT': 'ร่าง',
```

`frontend/src/journey.css` (tokens only — `journey.test.js` refuses a raw hex):

```css
/* Feedback Round 1 / WP1 — the PEAK source card */
.peak-card__applied { font-weight: 600; margin: var(--space-2) 0; }
.peak-card__apply { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; margin-top: var(--space-3); }
.peak-rows { margin-top: var(--space-4); }
.peak-rows__list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.peak-row { border: 1px solid var(--line); border-radius: var(--radius-md); padding: var(--space-3); }
.peak-row__facts { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: baseline; }
.peak-row__cands { list-style: none; margin: var(--space-2) 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.peak-row__confirm { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: end; margin-top: var(--space-2); }
```

Use the token names `tokens.css` actually defines (`grep -- '--space-\|--line\|--radius' frontend/src/tokens.css`); do not invent one.

Mount it in `frontend/src/screens/DataSourcesMigration.jsx`: import `{ PeakReportCard }` and render `<PeakReportCard />` immediately after the `</section>` that closes the crm.lead intake desk (the section containing `data-testid="manifest"`).

- [ ] **Step 5: Run the card's tests, the screen's tests, i18n parity and the CSS rule**

Run: `cd frontend && npx vitest run src/components/PeakReportCard.test.jsx src/screens/DataSourcesMigration.test.jsx src/i18n.test.js src/journey.test.js`
Expected: PASS — 6 new; the screen test is untouched because the card guards every binding it calls with `typeof api.x === 'function'` and renders its empty state.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.js frontend/src/components/PeakReportCard.jsx frontend/src/components/PeakReportCard.test.jsx frontend/src/screens/DataSourcesMigration.jsx frontend/src/i18n-admin.js frontend/src/journey.css
git commit -m "feat(data sources): the PEAK report card — a run to watch, a receipt, and the two lists a person links"
```

---

### Task 13: `PaymentPosition.jsx` on the case, the queue and the book

**Files:**
- Create: `frontend/src/components/PaymentPosition.jsx`, `frontend/src/components/PaymentPosition.test.jsx`
- Modify: `frontend/src/i18n-ops.js` (`pp.*` keys), `frontend/src/screens/CustomerCase.jsx:622` (after `MoneyPosition`), `frontend/src/screens/Today.jsx` (the row's money cell, after its `MoneyPosition`), `frontend/src/screens/WorkBook.jsx:448` (money column)
- Test: append one test each to `CustomerCase.test.jsx`, `Today.test.jsx`, `WorkBook.test.jsx` (additions)

**Interfaces:**
- Consumes: the served `payment_position` (Task 10).
- Produces: `<PaymentPosition pp={block} compact={bool} />`; test ids `payment-position`, `pp-source` (with `data-source`), `pp-stale`, `pp-asof-unknown`, `pp-oldest`, `pp-note`, `pp-counts`.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/PaymentPosition.test.jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { renderIn } from '../test-utils.jsx'
import { PaymentPosition } from './PaymentPosition.jsx'

const FULL = {
  paid_count: 11, open_count: 4, total_count: 15,
  oldest_unpaid: { uid: 'inv-00199', peak_number: 'IVT-20260400091', due_date: '2026-04-12', outstanding: '8399.00' },
  last_money_in: { amount: '38257.45', on: '2026-07-16', source: 'PEAK_REPORT', ref: 'RE-20260700272' },
  source: 'PEAK_REPORT', as_of: '2026-07-16', as_of_days: 57, stale: true,
  note_th: 'ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ 2026-07-16',
}

describe('PaymentPosition', () => {
  it('says how many invoices are paid and how many remain, as served', () => {
    renderIn('th', <PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-counts')).toHaveTextContent('11')
    expect(screen.getByTestId('pp-counts')).toHaveTextContent('4')
  })
  it('names the source so the officer knows who says this', () => {
    renderIn('th', <PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-source')).toHaveAttribute('data-source', 'PEAK_REPORT')
  })
  it('marks a stale position and never a fresh one', () => {
    renderIn('th', <PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
    renderIn('th', <PaymentPosition pp={{ ...FULL, stale: false, as_of_days: 3 }} />)
    expect(screen.getAllByTestId('pp-stale')).toHaveLength(1)
  })
  it('draws an unknown as-of as unknown, never as fresh', () => {
    renderIn('th', <PaymentPosition pp={{ ...FULL, as_of: null, as_of_days: null, stale: null }} />)
    expect(screen.getByTestId('pp-asof-unknown')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-stale')).toBeNull()
  })
  it('prints the served oldest-unpaid figure and computes nothing', () => {
    renderIn('th', <PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('8,399.00')
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('IVT-20260400091')
  })
  it('renders nothing when the API does not carry the block', () => {
    const { container } = render(<PaymentPosition pp={null} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('the compact variant keeps counts, source and the stale mark, and drops the note', () => {
    renderIn('th', <PaymentPosition pp={FULL} compact />)
    expect(screen.getByTestId('pp-counts')).toBeInTheDocument()
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-note')).toBeNull()
  })
})
```

Append to the three screen tests (each an ADDED `it`, using that file's own render helper and fixture — add `payment_position: FULL_PP` to the fixture item the way the file's other served keys are added):

```jsx
it('carries the payment position beside the money', async () => {
  renderCase()   // Today.test.jsx: renderToday(); WorkBook.test.jsx: renderBook()
  expect((await screen.findAllByTestId('payment-position')).length).toBeGreaterThan(0)
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/PaymentPosition.test.jsx`
Expected: FAIL — cannot resolve the component.

- [ ] **Step 3: Write the component and the strings**

```jsx
// frontend/src/components/PaymentPosition.jsx
import { useT } from '../prefs.jsx'
import { format } from './Money.jsx'
import { formatDate } from './NextAction.jsx'

// Plan 2026-09-11 §1.5, built in Feedback Round 1. Four questions in reading order:
// did they pay (counts), how much is left (oldest unpaid), when money last came in,
// and who says so and how fresh. Sits BESIDE StatusPair; never replaces it.
// Nothing here computes: every figure arrives quantised from payment_position.build.
export function PaymentPosition({ pp, compact = false }) {
  const t = useT()
  if (!pp || typeof pp !== 'object') return null
  const oldest = pp.oldest_unpaid
  const lastIn = pp.last_money_in
  return (
    <div className={`pp${compact ? ' pp--compact' : ''}`} data-testid="payment-position">
      <p className="pp__counts" data-testid="pp-counts">
        {t('pp.counts', { paid: pp.paid_count, open: pp.open_count, total: pp.total_count })}
      </p>
      {oldest && !compact && (
        <p className="pp__oldest" data-testid="pp-oldest">
          {t('pp.oldest', { amount: format(oldest.outstanding), ref: oldest.peak_number || oldest.uid, due: formatDate(oldest.due_date) || oldest.due_date || '—' })}
        </p>
      )}
      {lastIn && !compact && (
        <p className="pp__lastin" data-testid="pp-lastin">
          {t('pp.lastIn', { amount: format(lastIn.amount), on: formatDate(lastIn.on) || lastIn.on, ref: lastIn.ref })}
        </p>
      )}
      <p className="pp__prov">
        <span className="pp__source" data-testid="pp-source" data-source={pp.source}>{t(`pp.source.${pp.source}`)}</span>
        {pp.as_of
          ? <span className="pp__asof"> · {t('pp.asOf', { on: formatDate(pp.as_of) || pp.as_of, days: pp.as_of_days })}</span>
          : <span className="pp__asof pp__asof--unknown" data-testid="pp-asof-unknown"> · {t('pp.asOfUnknown')}</span>}
        {pp.stale === true && <span className="pp__stale" data-testid="pp-stale"> · {t('pp.stale')}</span>}
      </p>
      {!compact && pp.note_th && <p className="pp__note td-quiet" data-testid="pp-note">{pp.note_th}</p>}
    </div>
  )
}
```

`frontend/src/i18n-ops.js`, both tables:

```js
  'pp.counts': { en: 'Paid {paid} of {total} invoices · {open} open', th: 'จ่ายแล้ว {paid} จาก {total} ใบ · ค้าง {open} ใบ' },
  'pp.oldest': { en: 'Oldest unpaid {ref} · {amount} · due {due}', th: 'ค้างนานสุด {ref} · {amount} · ครบกำหนด {due}' },
  'pp.lastIn': { en: 'Last money in {amount} on {on} ({ref})', th: 'เงินเข้าล่าสุด {amount} เมื่อ {on} ({ref})' },
  'pp.source.SHEET': { en: 'from the sheet', th: 'จากชีต' },
  'pp.source.SLIP': { en: 'from a confirmed slip', th: 'จากสลิปที่ยืนยันแล้ว' },
  'pp.source.PEAK_DOC': { en: 'from a PEAK document', th: 'จากเอกสาร PEAK' },
  'pp.source.PEAK_REPORT': { en: 'from the PEAK invoice report', th: 'จากรายงานใบแจ้งหนี้ PEAK' },
  'pp.asOf': { en: 'as of {on} ({days} d)', th: 'ณ {on} ({days} วัน)' },
  'pp.asOfUnknown': { en: 'date unknown', th: 'ไม่ทราบวันที่' },
  'pp.stale': { en: 'stale', th: 'ข้อมูลเก่า' },
```

(Match the table's actual shape first — if `i18n-ops.js` is two flat objects `OPS_EN` / `OPS_TH` like `i18n-journey.js`, split the pairs into the two objects.)

Mount: `CustomerCase.jsx` after line 622's `<MoneyPosition …/>`: `<PaymentPosition pp={item?.payment_position} />`. `Today.jsx`: in `QueueRow`'s money cell after its `MoneyPosition`: `<PaymentPosition pp={item.payment_position} compact />`. `WorkBook.jsx:448` money column render: wrap `Money` and `<PaymentPosition pp={r.payment_position} compact />` in a fragment.

- [ ] **Step 4: Measure the ratchets BEFORE keeping the mounts**

Run: `cd frontend && npx vitest run src/density.test.jsx src/today-density.test.jsx`
Expected: PASS. The case page gains 4 elements pre-contact (div, p, p, span) — measured headroom is in Task 0's table; Today's row gains 3 (div, p, p·span) against the 31 cap. **If either fails, do not raise the cap:** on Today, render the compact variant as a single `<p>` (counts + source in one line, 2 elements) and re-measure; on the case page, drop `pp-lastin` (MoneyPosition already prints the money) and re-measure. Raising a ratchet is a test edit and needs a number from F17.

- [ ] **Step 5: Run the screen tests, the suite and the build**

Run: `cd frontend && npx vitest run && npx vite build`
Expected: PASS, baseline + 10. **Paste the count.**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PaymentPosition.jsx frontend/src/components/PaymentPosition.test.jsx frontend/src/i18n-ops.js frontend/src/screens/CustomerCase.jsx frontend/src/screens/Today.jsx frontend/src/screens/WorkBook.jsx frontend/src/screens/CustomerCase.test.jsx frontend/src/screens/Today.test.jsx frontend/src/screens/WorkBook.test.jsx
git commit -m "feat(ui): paid and open invoice counts, the oldest unpaid and who says so, on the case, the queue and the book"
```

---

### Task 14: The book acts on it — `position=unpaid|stale` and the `oldest_unpaid` sort

**Files:**
- Modify: `backend/app/routers/today.py:265` (`workbook` signature and filter)
- Modify: `frontend/src/screens/WorkBook.jsx:27` (`EMPTY_FILTERS`), `:158` (`SORTABLE`), the filter definitions near `:645`
- Test: `backend/tests/test_payment_position.py` (append), `frontend/src/screens/WorkBook.test.jsx` (append)

**Interfaces:**
- Produces: `GET /v1/workbook?position=unpaid|stale` (422 on any other value); sort key `oldest_unpaid` with accessor `r.payment_position?.oldest_unpaid?.due_date`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_book_filters_to_the_unpaid_and_to_the_stale():
    everyone = client.get("/v1/workbook").json()["rows"]
    unpaid = client.get("/v1/workbook?position=unpaid").json()["rows"]
    assert len(unpaid) <= len(everyone)
    assert all(r["payment_position"]["open_count"] > 0 for r in unpaid)
    stale = client.get("/v1/workbook?position=stale").json()["rows"]
    assert all(r["payment_position"]["stale"] is True for r in stale)


def test_an_unknown_position_filter_is_refused_not_ignored():
    assert client.get("/v1/workbook?position=banana").status_code == 422
```

```jsx
it('offers the unpaid and the stale as a filter', async () => {
  renderBook()
  expect(await screen.findByTestId('filter-position')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -k "book_filters or unknown_position" -v`
Expected: FAIL — `banana` returns 200; `unpaid` equals `everyone`.

- [ ] **Step 3: Implement**

`backend/app/routers/today.py`, `workbook(...)`: add `position: str = Query(default=None)` and, after the rows are projected and before `meta.total` is computed:

```python
    if position is not None:
        if position not in ("unpaid", "stale"):
            raise errors.validation_failed([{
                "pointer": "/position", "code": "value_unknown",
                "message": "position is 'unpaid' or 'stale'; %r is neither." % position,
                "message_th": "ตัวกรองสถานะการชำระรับเฉพาะ unpaid หรือ stale"}])
        # A filter that matched everything on a typo would be worse than an error.
        if position == "unpaid":
            rows = [r for r in rows if (r.get("payment_position") or {}).get("open_count")]
        else:
            rows = [r for r in rows if (r.get("payment_position") or {}).get("stale") is True]
```

Apply the same filter on the CLOSED-row path so `meta.total` and the CSV agree (the same rule `test_round4.py:765` explains).

`WorkBook.jsx`: `EMPTY_FILTERS` gains `position: ''`; `SORTABLE` gains `'oldest_unpaid'` with the accessor `(r) => r.payment_position?.oldest_unpaid?.due_date || ''` wherever the sort accessors live; the filter bar gains `{ key: 'position', label: t('book.filter.position'), options: [{ value: 'unpaid', label: t('book.position.unpaid') }, { value: 'stale', label: t('book.position.stale') }], value: filters.position }` following the exact shape of the `payment_status` filter beside it. Strings in `i18n-ops.js` (EN/TH): `book.filter.position` "Payment position" / "สถานะการชำระ (PEAK/ชีต)", `book.position.unpaid` "Has unpaid invoices" / "มีใบค้างชำระ", `book.position.stale` "Position is stale" / "ข้อมูลการชำระเก่า".

- [ ] **Step 4: Run everything**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED. **Paste backend / frontend / e2e counts.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/today.py backend/tests/test_payment_position.py frontend/src/screens/WorkBook.jsx frontend/src/screens/WorkBook.test.jsx frontend/src/i18n-ops.js
git commit -m "feat(book): filter and sort the book by the payment position"
```

---

## WP2 — Import "new only"

### Task 15: The writer's `NEW_ONLY` mode and the proposals ledger

**Files:**
- Modify: `backend/app/pipelines/writer.py` (`write` gains `mode`; new `_resolve_existing`)
- Test: `backend/tests/test_import_new_only.py` (create)

**Interfaces:**
- Consumes: `landing.customer` SHEET rows from OK runs; the writer's record shape (`volt_id, customer_no, phone_e164, name_*, order, reason`).
- Produces: `writer.write(conn, records, verdicts, batch=1000, on_progress=None, read=None, door=None, mode="OVERWRITE")` — **the writer's default stays OVERWRITE** so every existing writer test keeps its meaning; the service and router (Task 16) default to `NEW_ONLY`. In `NEW_ONLY` the result gains `new`, `skipped`, `proposals` (list) and `import_run.meta` gains `mode`, `new`, `skipped`, `proposals`. A proposal is `{"kind": "FIELDS_DIFFER" | "NEW_CONTRACT_FOR_EXISTING", "customer_no", "sheet_volt_id", "odoo_volt_id", "matched_by", "fields": [{"field", "sheet", "odoo"}]}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_import_new_only.py
"""Design F6 / the manager's ask: a crm.lead run adds customers the platform has never
seen and leaves every existing customer and contract exactly as it is. What differs
is written down as a proposal, never applied."""
import pytest
from sqlalchemy import text

from app import landing, migrate
from app.pipelines import writer
from tests.test_pipeline_writer import _record


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def _sheet(conn, volt_id, customer_no, phone=None, **fields):
    run = landing.start_run(conn, "SHEET")
    landing.write_customer(conn, run, "SHEET", dict({"volt_id": volt_id, "customer_no": customer_no,
                                                    "name_th": "ชื่อจากชีต", "epc": "SLT", "product": "LEASE",
                                                    "phone_e164": phone, "source_refs": []}, **fields))
    landing.finish_run(conn, run, "OK")


def _odoo_rows(conn):
    return conn.execute(text("select volt_id from landing.customer where data_source='ODOO' order by volt_id")).scalars().all()


def test_new_only_lands_only_the_leads_nobody_holds(schema):
    _sheet(schema, "28005096535_Manop_มานพ_IPW", "28005096535", phone="0812345678")
    result = writer.write(schema, [_record("28005096535"), _record("VL0009999")], [], mode="NEW_ONLY")
    assert (result["new"], result["skipped"]) == (1, 1)
    assert _odoo_rows(schema) == ["VL0009999"]


def test_an_existing_customer_is_found_by_customer_number_phone_or_v_id_prefix(schema):
    _sheet(schema, "99999000328_Somchai_สมชาย_SLT", "28006083653", phone="0898765432")
    by_no = _record("28006083653")
    by_phone = dict(_record("VL0000001"), phone_e164="+66898765432")
    by_vid = _record("99999000328")
    result = writer.write(schema, [by_no, by_phone, by_vid], [], mode="NEW_ONLY")
    assert result["skipped"] == 3 and _odoo_rows(schema) == []
    assert {p["matched_by"] for p in result["proposals"]} <= {"CUSTOMER_NO", "PHONE", "VOLT_ID"}


def test_a_differing_field_becomes_a_proposal_with_both_values_and_nothing_moves(schema):
    _sheet(schema, "VL0000143_x", "VL0000143", epc="SLT")
    result = writer.write(schema, [_record("VL0000143")], [], mode="NEW_ONLY")     # _record's epc is IPW
    prop = next(p for p in result["proposals"] if p["kind"] == "FIELDS_DIFFER")
    assert {"field": "epc", "sheet": "SLT", "odoo": "IPW"} in prop["fields"]
    assert schema.execute(text("select epc from landing.customer where data_source='SHEET'")).scalar() == "SLT"


def test_a_new_v_id_on_an_old_phone_is_a_new_contract_proposal(schema):
    _sheet(schema, "VC0000001_old", "28000000001", phone="0812345678")
    lead = dict(_record("VC0009999"), phone_e164="0812345678")
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    assert result["skipped"] == 1
    assert result["proposals"][0]["kind"] == "NEW_CONTRACT_FOR_EXISTING"
    assert result["proposals"][0]["odoo_volt_id"] == "VC0009999"


def test_overwrite_mode_behaves_exactly_as_before(schema):
    _sheet(schema, "VL0000143_x", "VL0000143", epc="SLT")
    result = writer.write(schema, [_record("VL0000143")], [], mode="OVERWRITE")
    assert result["overwrote"] >= 1 and "VL0000143" in _odoo_rows(schema)


def test_the_run_receipt_says_which_mode_ran(schema):
    result = writer.write(schema, [_record("VL0000143")], [], mode="NEW_ONLY")
    meta = schema.execute(text("select meta from landing.import_run where id=:i"), {"i": result["run_id"]}).scalar()
    assert meta["mode"] == "NEW_ONLY" and meta["new"] == 1 and meta["skipped"] == 0 and meta["proposals"] == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_import_new_only.py -v`
Expected: FAIL — `write() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Implement the mode**

In `backend/app/pipelines/writer.py`, add after `_sheet_rows`:

```python
import re

from .peak_match import normalise_code, _digits as _phone_digits   # one normaliser, not two

_VID = re.compile(r"^(V[A-Z]{1,2}\d{7})")

MODES = ("NEW_ONLY", "OVERWRITE")


def _sheet_index(conn):
    """Every SHEET customer from an OK run, indexed three ways. This is §1 of the rules
    file finally applied (rows 1–3: customer number, phone, V-id prefix), the keys the
    2026-09-11 comparison measured at 58/58, 58/58 and 0/58-exact."""
    rows = conn.execute(text(
        "select t.* from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'SHEET'")).mappings().all()
    by_no, by_phone, by_vid = {}, {}, {}
    for r in rows:
        r = dict(r)
        if r.get("customer_no"):
            by_no[str(r["customer_no"])] = r
        ph = _phone_digits(r.get("phone_e164"))
        if ph:
            by_phone[ph] = r
        m = _VID.match(normalise_code(r.get("volt_id")))
        if m:
            by_vid[m.group(1)] = r
    return by_no, by_phone, by_vid


def _resolve_existing(index, record):
    """(sheet_row, matched_by) for a lead the book already holds, else (None, None)."""
    by_no, by_phone, by_vid = index
    no = str(record.get("customer_no") or "")
    if no and no in by_no:
        return by_no[no], "CUSTOMER_NO"
    vid = normalise_code(record.get("volt_id"))
    m = _VID.match(vid)
    if m and m.group(1) in by_vid:
        return by_vid[m.group(1)], "VOLT_ID"
    ph = _phone_digits(record.get("phone_e164"))
    if ph and ph in by_phone:
        return by_phone[ph], "PHONE"
    return None, None


def _proposal(sheet, record, matched_by):
    fields = []
    for field in LEDGER_FIELDS:
        old, new = sheet.get(field), record.get(field)
        if old not in (None, "") and new not in (None, "") and old != new:
            fields.append({"field": field, "sheet": old, "odoo": new})
    sheet_vid = _VID.match(normalise_code(sheet.get("volt_id")))
    odoo_vid = _VID.match(normalise_code(record.get("volt_id")))
    kind = "FIELDS_DIFFER"
    if odoo_vid and matched_by != "VOLT_ID" and (not sheet_vid or sheet_vid.group(1) != odoo_vid.group(1)):
        kind = "NEW_CONTRACT_FOR_EXISTING"       # the package-change trace, reported not applied
    return {"kind": kind, "customer_no": sheet.get("customer_no"), "sheet_volt_id": sheet.get("volt_id"),
            "odoo_volt_id": record.get("volt_id"), "matched_by": matched_by, "fields": fields}
```

Then change `write`'s signature to `def write(conn, records, verdicts, batch=1000, on_progress=None, read=None, door=None, mode="OVERWRITE"):` and, right after `run = landing.start_run(conn, "ODOO")`:

```python
    if mode not in MODES:
        raise ValueError("mode is NEW_ONLY or OVERWRITE, not %r" % mode)
    proposals, skipped = [], 0
    if mode == "NEW_ONLY":
        index = _sheet_index(conn)
        kept = []
        for record in records:
            sheet, matched_by = _resolve_existing(index, record)
            if sheet is None:
                kept.append(record)
                continue
            skipped += 1
            prop = _proposal(sheet, record, matched_by)
            if prop["fields"] or prop["kind"] == "NEW_CONTRACT_FOR_EXISTING":
                proposals.append(prop)
        records = kept
```

(so the existing `before = _sheet_rows(...)` ledger runs only over what is still written), and add to the `meta` json and the returned dict: `"mode": mode, "new": landed if mode == "NEW_ONLY" else None, "skipped": skipped, "proposals": proposals` (meta) and `"new": landed, "skipped": skipped, "proposals": proposals` (result). `row_counts` gains `"skipped": skipped`.

- [ ] **Step 4: Run the new tests and the writer's existing ones**

Run: `cd backend && python -m pytest tests/test_import_new_only.py tests/test_pipeline_writer.py -v`
Expected: PASS — the existing writer tests still run in OVERWRITE (the default) and do not move.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/writer.py backend/tests/test_import_new_only.py
git commit -m "feat(pipelines): NEW_ONLY lands only leads the book does not hold, and writes what differs as proposals"
```

---

### Task 16: The mode through the service and the router, defaulting to `NEW_ONLY`

**Files:**
- Modify: `backend/app/pipelines/service.py` (`_land`, `run_odoo`, `run_upload` take `mode`)
- Modify: `backend/app/pipelines/schedule.py` (the timer calls `run_odoo(mode="NEW_ONLY")`)
- Modify: `backend/app/routers/pipelines.py` (`_read_source` returns the mode; `:run`, `:start`; `_receipt_summary` gains the three counts and a proposals sample)
- Test: `backend/tests/test_pipeline_router.py` (append), `backend/tests/test_pipeline_service.py` (append)

**Interfaces:**
- Produces: `POST /v1/pipelines/crm-lead:run|:start` accept `{"source": "odoo", "mode": "NEW_ONLY"|"OVERWRITE"}` (JSON door) or the header `X-Volt-Import-Mode` (upload door); **default `NEW_ONLY`**; an unknown mode is a 422. `GET …/last-run` and `…/landing-runs/{id}` receipts carry `mode`, `new`, `skipped`, `proposals_total`, `proposals_sample` (first 20).

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_pipeline_router.py
def test_the_default_mode_is_new_only_and_an_unknown_mode_is_refused():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"}, headers=MANAGER)
    assert r.status_code == 202 and r.json()["mode"] == "NEW_ONLY"
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo", "mode": "SOMETHING"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/mode"
```

```python
# append to backend/tests/test_pipeline_service.py
def test_the_run_view_carries_the_mode_it_ran_in(monkeypatch):
    from app.pipelines import service, runs
    monkeypatch.setattr(service, "_land", lambda uid, raw_rows, rules, door=None, mode=None: {
        "run_id": 1, "landed": 0, "rejected": 0, "overwrote": 0, "read": 0, "door": door, "ledger": [],
        "mode": mode, "new": 0, "skipped": 0, "proposals": []})
    monkeypatch.setattr(service.rules_mod, "load", lambda: object())
    monkeypatch.setattr(service.ingress, "from_upload", lambda raw, filename, rules: [])
    run = service.run_upload(b"x", "x.csv", mode="OVERWRITE")
    assert run["result"]["mode"] == "OVERWRITE" and run["mode"] == "OVERWRITE"
```

(`MANAGER` is the header dict the file already defines for its Manager requests — reuse its name.)

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_pipeline_router.py tests/test_pipeline_service.py -v`
Expected: FAIL — `mode` missing from the run view; `SOMETHING` accepted.

- [ ] **Step 3: Thread the mode through**

`service.py`: `_land(uid, raw_rows, rules, door=None, mode="NEW_ONLY")` passes `mode=mode` to `writer.write`; `run_odoo(uid=None, mode="NEW_ONLY")` and `run_upload(raw, filename, uid=None, mode="NEW_ONLY")` pass it on and call `runs.progress(uid, mode=mode)` right after `runs.start` so the view carries it. `schedule.py`'s timer call becomes `service.run_odoo(mode="NEW_ONLY")`.

`routers/pipelines.py`: `_read_source(raw, is_json, x_volt_filename, x_volt_import_mode=None)` returns `(door, filename, mode)`, where the mode is `body.get("mode")` for the JSON door and the header for the upload door, defaulting to `"NEW_ONLY"`; anything not in `writer.MODES` raises `errors.validation_failed([{"pointer": "/mode", "code": "invalid", "message": "mode is NEW_ONLY or OVERWRITE", "message_th": "mode ต้องเป็น NEW_ONLY หรือ OVERWRITE"}])`. Both routes read `x_volt_import_mode: str = Header(default=None)`, pass `mode` into `service.run_upload(raw, filename, uid, mode)` / `service.run_odoo(uid, mode)` / `writer.write(..., mode=mode)`, and `:start`'s 202 body is `{**runs.get(uid), "mode": mode}`. `_receipt_summary` adds:

```python
        "mode": meta.get("mode") or "OVERWRITE",
        "new": meta.get("new"), "skipped": meta.get("skipped"),
        "proposals_total": len(meta.get("proposals") or []),
        "proposals_sample": (meta.get("proposals") or [])[:20],
```

- [ ] **Step 4: Run the pipeline suite**

Run: `cd backend && python -m pytest tests/test_pipeline_router.py tests/test_pipeline_service.py tests/test_pipeline_schedule.py tests/test_pipeline_receipt.py -v`
Expected: PASS. If `test_pipeline_schedule.py` asserts the exact call `run_odoo()` with no arguments, stop: that is a pinned test and the price goes to Arina (F17) before anything is edited.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/service.py backend/app/pipelines/schedule.py backend/app/routers/pipelines.py backend/tests/test_pipeline_router.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipelines): a run names its mode, NEW_ONLY unless a Manager says OVERWRITE"
```

---

### Task 17: The manifest says new · untouched · differs, and lists the proposals

**Files:**
- Modify: `frontend/src/screens/DataSourcesMigration.jsx` (the crm.lead manifest rows near `:469-480`; the receipt detail near `:653-670`; the ขั้นสูง fold)
- Modify: `frontend/src/api.js:323-331` (`crmLeadRun`/`crmLeadStart` pass a mode)
- Modify: `frontend/src/i18n-admin.js` (`mig.mode*`, `mig.new`, `mig.skipped`, `mig.proposals*` keys)
- Test: `frontend/src/screens/DataSourcesMigration.test.jsx` (append — additions with the file's own mocks)

**Interfaces:**
- Consumes: Task 16's receipt fields.
- Produces: three manifest rows (`mig-new`, `mig-skipped`, `mig-proposals` test ids), a proposals list (`mig-proposal-<customer_no>`), and a mode select under ขั้นสูง (`mig-mode`) that only a Manager sees.

- [ ] **Step 1: Write the failing tests** (append to `DataSourcesMigration.test.jsx`; add `crmLeadLastRun`, `crmLeadLandingRun` to the mocked `api` if the file does not already mock them, following its `mocks.x()` pattern)

```jsx
it('the receipt says how many leads were new, how many were left untouched, and how many differ', async () => {
  mocks.crmLeadLastRun = () => Promise.resolve({ run: { id: 3, source_system: 'ODOO', status: 'OK', meta: { door: 'odoo', mode: 'NEW_ONLY', new: 120, skipped: 34081, proposals: [
    { kind: 'FIELDS_DIFFER', customer_no: '28005096535', sheet_volt_id: '28005096535_x', odoo_volt_id: '99999000328', matched_by: 'CUSTOMER_NO', fields: [{ field: 'epc', sheet: 'SLT', odoo: 'IPW' }] }] } },
    watch: null, receipt: { id: 3, mode: 'NEW_ONLY', new: 120, skipped: 34081, proposals_total: 1, proposals_sample: [
    { kind: 'FIELDS_DIFFER', customer_no: '28005096535', matched_by: 'CUSTOMER_NO', fields: [{ field: 'epc', sheet: 'SLT', odoo: 'IPW' }] }], counts: {}, rejected_by_rule: {}, unmapped_sample: [], ledger_sample: [] } })
  renderIn('th', <DataSourcesMigration />)
  expect(await screen.findByTestId('mig-new')).toHaveTextContent('120')
  expect(screen.getByTestId('mig-skipped')).toHaveTextContent('34,081')
  expect(screen.getByTestId('mig-proposals')).toHaveTextContent('1')
  expect(screen.getByTestId('mig-proposal-28005096535')).toHaveTextContent('epc')
})

it('the mode is NEW_ONLY unless a Manager opens ขั้นสูง and picks OVERWRITE', async () => {
  setRole('MANAGER')
  renderIn('th', <DataSourcesMigration />)
  const fold = await screen.findByText('ขั้นสูง')
  fireEvent.click(fold)
  expect(screen.getByTestId('mig-mode')).toHaveTextContent('เฉพาะลูกค้าใหม่')
})
```

(`setRole` comes from `../components/role.jsx`; import it if the file does not already.)

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/screens/DataSourcesMigration.test.jsx`
Expected: FAIL — `mig-new` not found.

- [ ] **Step 3: Implement**

`api.js`: `crmLeadRun: (file, mode) => …` and `crmLeadStart: (file, mode) => …` — the JSON door sends `{ source: 'odoo', mode }`; the upload door needs a header, so extend `postRaw(path, file, extraHeaders = {})` to spread `extraHeaders` into its headers and pass `{ 'X-Volt-Import-Mode': mode }` when `mode` is given.

`DataSourcesMigration.jsx`: a `mode` state (`'NEW_ONLY'` default) rendered as a `SearchSelect` with test id `mig-mode` inside the existing ขั้นสูง `<details>`, options `NEW_ONLY` → `t('mig.mode.NEW_ONLY')`, `OVERWRITE` → `t('mig.mode.OVERWRITE')`, visible only when `['MANAGER','OWNER'].includes(role)`; passed to both `api.crmLeadStart(file, mode)` and `api.crmLeadRun(uid)` calls. In the manifest's `<dl className="manifest__rows">`, three more rows reading `receipt.new`, `receipt.skipped`, `receipt.proposals_total` with the test ids above, printed with `toLocaleString('en-US')`, a dash when null. Under the receipt detail, a `<ul data-testid="mig-proposals-list">` of `receipt.proposals_sample`, each `<li data-testid={`mig-proposal-${p.customer_no}`}>` printing `t(`mig.proposal.${p.kind}`)`, the `matched_by` rule in mono, and `p.fields.map(f => `${f.field}: ${f.sheet} → ${f.odoo}`)`.

`i18n-admin.js` (EN / TH): `mig.new` "New customers landed" / "ลูกค้าใหม่ที่นำเข้า"; `mig.skipped` "Existing, left untouched" / "ลูกค้าเดิม ไม่แตะ"; `mig.proposals` "Differences to review" / "รายการที่ต่างจากชีต"; `mig.mode.NEW_ONLY` "New customers only (existing untouched)" / "เฉพาะลูกค้าใหม่ (ไม่แตะลูกค้าเดิม)"; `mig.mode.OVERWRITE` "Overwrite existing with Odoo (ledger kept)" / "เขียนทับลูกค้าเดิมด้วย Odoo (บันทึกรายการเขียนทับ)"; `mig.modeLabel` "Import mode" / "โหมดนำเข้า"; `mig.proposal.FIELDS_DIFFER` "Fields differ" / "ค่าต่างจากชีต"; `mig.proposal.NEW_CONTRACT_FOR_EXISTING` "New contract for an existing customer" / "สัญญาใหม่ของลูกค้าเดิม".

- [ ] **Step 4: Run the screen tests, i18n parity, then everything**

Run: `cd frontend && npx vitest run src/screens/DataSourcesMigration.test.jsx src/i18n.test.js && cd .. && ./scripts/verify_all.sh`
Expected: PASS. **Paste the counts.**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/DataSourcesMigration.jsx frontend/src/api.js frontend/src/i18n-admin.js frontend/src/screens/DataSourcesMigration.test.jsx
git commit -m "feat(data sources): the receipt says new, untouched and differs; OVERWRITE waits under ขั้นสูง"
```

---

## WP3 — Scorecard first, month strip second, in the dialog too

### Task 18: `PaymentOverview` reordered — the contract scorecard first, with the invoice counts

**Files:**
- Modify: `frontend/src/components/PaymentOverview.jsx` (the `PaymentOverview` export; add `compact` and `position` props)
- Modify: `frontend/src/i18n-journey.js` (`payov.invoices*`, `payov.source.*`, `payov.lastIn`)
- Test: `frontend/src/components/PaymentOverview.test.jsx` (append — additions only)

**Interfaces:**
- Consumes: `payment_summary` (with Task 9's `source`/`peak` per contract) and `payment_position` (Task 10).
- Produces: `<PaymentOverview summary={…} position={…} compact={false} />`. Reading order: **scorecard** (paid so far / of total · overdue · **invoices paid n / open m** · last money in · source line) then the strip(s), then the fold. `compact` renders the scorecard only, in one row, with `data-testid="payov-compact"`.

- [ ] **Step 1: Write the failing tests** (append to `PaymentOverview.test.jsx`, using the file's own `SUMMARY` fixture name — read it first)

```jsx
const POSITION = { paid_count: 11, open_count: 4, total_count: 15, oldest_unpaid: null,
  last_money_in: { amount: '38257.45', on: '2026-07-16', source: 'PEAK_REPORT', ref: 'RE-20260700272' },
  source: 'PEAK_REPORT', as_of: '2026-07-16', as_of_days: 57, stale: true, note_th: 'x' }

it('puts the scorecard before the strip, with the paid and open invoice counts and the last money in', () => {
  renderIn('th', <PaymentOverview summary={SUMMARY} position={POSITION} />)
  const card = screen.getByTestId('payment-overview')
  const order = [...card.querySelectorAll('[data-testid]')].map((n) => n.getAttribute('data-testid'))
  expect(order.indexOf('payov-invoices')).toBeLessThan(order.findIndex((id) => id.startsWith('payov-legend-')))
  expect(screen.getByTestId('payov-invoices')).toHaveTextContent('11')
  expect(screen.getByTestId('payov-invoices')).toHaveTextContent('4')
  expect(screen.getByTestId('payov-lastin')).toHaveTextContent('38,257.45')
})

it('names the source of the picture — PEAK when a contract is drawn from PEAK, the sheet otherwise', () => {
  renderIn('th', <PaymentOverview summary={{ ...SUMMARY, contracts: SUMMARY.contracts.map((k) => ({ ...k, source: 'PEAK', peak: { invoices: 12, report_as_of: '2026-09-14' } })) }} position={POSITION} />)
  expect(screen.getByTestId('payov-source')).toHaveTextContent('PEAK')
  expect(screen.getByTestId('payov-source')).toHaveTextContent('14/09/2026')
})

it('the compact variant is the scorecard alone', () => {
  renderIn('th', <PaymentOverview summary={SUMMARY} position={POSITION} compact />)
  expect(screen.getByTestId('payov-compact')).toBeInTheDocument()
  expect(screen.queryByTestId('payov-each')).toBeNull()
})

it('without a position the counts tile is absent, never zero', () => {
  renderIn('th', <PaymentOverview summary={SUMMARY} />)
  expect(screen.queryByTestId('payov-invoices')).toBeNull()
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/PaymentOverview.test.jsx`
Expected: FAIL — `payov-invoices` not found.

- [ ] **Step 3: Reorder and extend**

In `PaymentOverview`'s signature add `position = null, compact = false`. Build the scorecard as its own element and render it first:

```jsx
  const peakContract = contracts.find((k) => k.source === 'PEAK')
  const sourceLine = peakContract
    ? t('payov.source.PEAK', { date: formatDate(peakContract.peak?.report_as_of) || '—' })
    : t('payov.source.SHEET')
  const scorecard = (
    <dl className={`cs-pay__tiles${compact ? ' cs-pay__tiles--compact' : ''}`}>
      <div className="cs-pay__tile" data-testid="payov-paid">
        <dt>{t('payov.paidSoFar')}</dt>
        <dd>{format(totals.paid_amount)} <span className="cs-pay__sub">{t('payov.ofTotal', { total: format(totals.contract_amount) })}</span></dd>
      </div>
      <div className={`cs-pay__tile${Number(counts.OVERDUE ?? 0) > 0 ? ' cs-pay__tile--overdue' : ''}`} data-testid="payov-overdue">
        <dt>{t('payov.overdue')}</dt>
        <dd>{format(totals.overdue_amount)} <span className="cs-pay__sub">{t('payov.overdueCycles', { n: counts.OVERDUE ?? 0 })}</span></dd>
      </div>
      {position && (
        <div className="cs-pay__tile" data-testid="payov-invoices">
          <dt>{t('payov.invoices')}</dt>
          <dd>{t('payov.invoicesCounts', { paid: position.paid_count, open: position.open_count })}</dd>
        </div>
      )}
      {position?.last_money_in && (
        <div className="cs-pay__tile" data-testid="payov-lastin">
          <dt>{t('payov.lastIn')}</dt>
          <dd>{format(position.last_money_in.amount)} <span className="cs-pay__sub">{formatDate(position.last_money_in.on) || position.last_money_in.on}</span></dd>
        </div>
      )}
      <div className="cs-pay__tile" data-testid="payov-cycles">
        <dt>{t('payov.cyclesPaid')}</dt>
        <dd>{t('payov.cyclesOf', { paid: counts.PAID ?? 0, total: totals.cycle_count ?? 0 })}</dd>
      </div>
    </dl>
  )
  if (compact) {
    return (
      <div className="cs-pay cs-pay--compact" data-testid="payov-compact">
        {scorecard}
        <p className="td-quiet" data-testid="payov-source">{sourceLine}</p>
      </div>
    )
  }
```

and in the full render put `{scorecard}` and `<p className="td-quiet" data-testid="payov-source">{sourceLine}</p>` directly under the `<h2>`, before `{several && …}`. Keep every existing test id where it is (`payov-paid`, `payov-overdue`, `payov-cycles` are inside the scorecard, so the existing tests that read them still pass).

`i18n-journey.js` (EN block, then TH): `payov.invoices` "Invoices" / "ใบแจ้งหนี้"; `payov.invoicesCounts` "paid {paid} · open {open}" / "จ่ายแล้ว {paid} ใบ · ค้าง {open} ใบ"; `payov.lastIn` "Last money in" / "เงินเข้าล่าสุด"; `payov.source.PEAK` "Drawn from the PEAK invoice report as of {date}" / "วาดจากรายงานใบแจ้งหนี้ PEAK ณ {date}"; `payov.source.SHEET` "Drawn from the sheet, walked back by the app's schedule (indicative)" / "วาดจากชีต โดยเดินย้อนตามตารางผ่อนของแอป (ตัวเลขชี้แนะ)".

Mount the position on the case page: `CustomerCase.jsx:736` becomes `<PaymentOverview summary={data.payment_summary} position={item?.payment_position} />`.

- [ ] **Step 4: Measure the case-page ratchet, then run the suite**

Run: `cd frontend && npx vitest run src/density.test.jsx src/components/PaymentOverview.test.jsx && npx vitest run`
Expected: PASS. The scorecard adds two tiles (2 × 3 elements) when a position is served; the density fixture serves none (`payment_position` absent from its fixture) so the census does not move — **which means the real page is not measured by it.** Measure the real cost once by adding `payment_position: POSITION` to the density fixture ONLY in a scratch copy (do not commit the edit): if the worked case exceeds 123, drop `payov-lastin` from the case page (MoneyPosition already prints money) and keep it compact-only. Record the number here.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PaymentOverview.jsx frontend/src/components/PaymentOverview.test.jsx frontend/src/i18n-journey.js frontend/src/screens/CustomerCase.jsx
git commit -m "feat(overview): the contract scorecard first — paid, overdue, invoices paid and open, last money in, and which source drew it"
```

---

### Task 19: The scorecard inside the Save-contact dialog

**Files:**
- Modify: `frontend/src/components/CaseContactDrawer.jsx` (props `paymentSummary`, `paymentPosition`; lazy fetch for Today's drawer; the mount under the "ติดต่อล่าสุด" block near `:698`)
- Modify: `frontend/src/screens/CustomerCase.jsx:1853` (pass the two props), `frontend/src/screens/Today.jsx:1165` (nothing to pass; the drawer fetches)
- Test: `frontend/src/components/CaseContactDrawer.test.jsx` (append)

**Interfaces:**
- Produces: `<CaseContactDrawer … paymentSummary={summary} paymentPosition={pp} />`; when neither is given and `api.caseDetail` exists, the drawer fetches `/v1/cases/by-customer/{uid}` once and uses `payment_summary` + `work_item.payment_position` from it.

- [ ] **Step 1: Write the failing tests** (append; the file's `api` mock gains `caseDetail: vi.fn()` — an addition to the mock object, not to any existing assertion)

```jsx
it('shows the compact scorecard before the form when the case page hands it in', async () => {
  renderIn('th', <Drawer paymentSummary={{ contracts: [{ contract_uid: 'K-1', cycles: [{ n: 1, kind: 'INSTALMENT', due_date: '2026-01-10', amount: '1', paid: '1', outstanding: '0', status: 'PAID', partly_paid: false, source: 'SHEET_DERIVED' }], counts: { PAID: 1, OVERDUE: 0, UPCOMING: 0, NO_AMOUNT: 0 }, contract_amount: '1', paid_amount: '1', outstanding_amount: '0', overdue_amount: '0', source: 'SHEET_DERIVED', peak: null }], totals: { cycle_count: 1, counts: { PAID: 1, OVERDUE: 0, UPCOMING: 0, NO_AMOUNT: 0 }, contract_amount: '1', paid_amount: '1', outstanding_amount: '0', overdue_amount: '0' }, indicative: true, provenance_th: 'x' }}
                        paymentPosition={{ paid_count: 3, open_count: 1, total_count: 4, oldest_unpaid: null, last_money_in: null, source: 'SHEET', as_of: null, as_of_days: null, stale: null, note_th: 'x' }} />)
  expect(await screen.findByTestId('payov-compact')).toBeInTheDocument()
  expect(screen.getByTestId('payov-invoices')).toHaveTextContent('3')
})

it('fetches the case once when opened from Today, and renders nothing about money it did not get', async () => {
  api.caseDetail.mockResolvedValue({ payment_summary: null, work_item: { payment_position: null } })
  renderIn('th', <Drawer />)
  await waitFor(() => expect(api.caseDetail).toHaveBeenCalledWith('cu-1'))
  expect(screen.queryByTestId('payov-compact')).toBeNull()
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/CaseContactDrawer.test.jsx`
Expected: FAIL — `payov-compact` not found.

- [ ] **Step 3: Mount it**

In `CaseContactDrawer`'s signature add `paymentSummary = null, paymentPosition = null`; add

```jsx
  const [fetched, setFetched] = useState(null)
  useEffect(() => {
    if (paymentSummary || paymentPosition || typeof api.caseDetail !== 'function') return
    let alive = true
    api.caseDetail(customer.uid).then((d) => { if (alive) setFetched(d) }).catch(() => {})
    return () => { alive = false }
  }, [customer.uid, paymentSummary, paymentPosition])
  const summary = paymentSummary || fetched?.payment_summary || null
  const position = paymentPosition || fetched?.work_item?.payment_position || null
```

and directly after the `<div className="cd-section">` that holds `cd-history-last-contact` (still above the lock notice and the form), render `{summary && <PaymentOverview summary={summary} position={position} compact />}` (import it). `CustomerCase.jsx:1853` passes `paymentSummary={data.payment_summary} paymentPosition={item?.payment_position}`.

- [ ] **Step 4: Measure, then run the suite and the build**

Run: `cd frontend && npx vitest run src/density.test.jsx && npx vitest run && npx vite build`
Expected: PASS. The density census measures the page with the drawer closed (check `density.test.jsx`'s "worked case" setup — if it opens the drawer, the compact scorecard's elements count and the number goes in the table; over the cap means F17 before anything else). **Paste the count.**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CaseContactDrawer.jsx frontend/src/components/CaseContactDrawer.test.jsx frontend/src/screens/CustomerCase.jsx
git commit -m "feat(dialog): the contract scorecard before the officer dials"
```

---

## WP4 — Notes, attachments and history in the Save-contact dialog

### Task 20: `records.attachment` and the file guard — `attachments/guard.py`

**Files:**
- Modify: `backend/app/schema.sql` (append `records.attachment`)
- Modify: `backend/app/config.py` (`attachment_max_bytes: int = 10 * 1024 * 1024`, `attachments_per_note: int = 5`)
- Create: `backend/app/attachments/__init__.py` (empty), `backend/app/attachments/guard.py`
- Test: `backend/tests/test_attachments_guard.py` (create)

**Interfaces:**
- Produces: `guard.check(raw: bytes, filename: str) -> {"kind": "PNG"|"SVG"|"CSV"|"XLSX"|"DOCX"|"PDF", "content_type": str, "sha256": str, "size": int, "filename": str}`; raises `guard.Refused(code, detail, detail_th, rule)`. Codes: `too_large`, `type_not_allowed`, `extension_mismatch`, `png_corrupt`, `svg_active_content`, `csv_formula_cell`, `office_macro`, `office_external`, `office_zip_bomb`, `pdf_active_content`, `empty`. Consumed by Tasks 21, 22.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_attachments_guard.py
"""The file guard (vault note 10 §3 WP4, F8): a file is stored only after every rule
for its type passes, and a refusal names the rule. Standard library only."""
import io
import struct
import zipfile
import zlib

import pytest

from app import xlsx_writer
from app.attachments import guard


def _png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _zip(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


CT = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'
DOCX = {"[Content_Types].xml": CT, "word/document.xml": "<w:document><w:body>hello</w:body></w:document>"}


def test_a_well_formed_png_passes_and_a_corrupt_one_is_refused():
    out = guard.check(_png(), "site.png")
    assert out["kind"] == "PNG" and out["content_type"] == "image/png" and len(out["sha256"]) == 64
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png()[:-3], "site.png")
    assert exc.value.code == "png_corrupt"


def test_an_extension_that_disagrees_with_the_bytes_is_refused():
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png(), "site.pdf")
    assert exc.value.code == "extension_mismatch"


def test_svg_with_a_script_or_a_handler_or_an_external_href_is_refused():
    assert guard.check(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>', "a.svg")["kind"] == "SVG"
    for bad in (b'<svg><script>1</script></svg>', b'<svg onload="x()"></svg>',
                b'<svg><a href="javascript:1"/></svg>', b'<svg><image href="http://x/y.png"/></svg>',
                b'<svg><foreignObject/></svg>', b'<!DOCTYPE svg [<!ENTITY x "y">]><svg/>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_csv_with_a_formula_cell_is_refused_and_the_cell_is_named():
    assert guard.check("ชื่อ,ยอด\nมานพ,100\n".encode("utf-8"), "a.csv")["kind"] == "CSV"
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"name,amount\nx,=1+1\n", "a.csv")
    assert exc.value.code == "csv_formula_cell" and "B2" in exc.value.detail


def test_xlsx_and_docx_pass_and_macros_external_links_and_dde_are_refused():
    assert guard.check(xlsx_writer.workbook([{"name": "s", "rows": [["a"]]}]), "a.xlsx")["kind"] == "XLSX"
    assert guard.check(_zip(DOCX), "a.docx")["kind"] == "DOCX"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/vbaProject.bin": b"\x00"}), "a.docx")
    assert exc.value.code == "office_macro"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/document.xml": '<w:instrText> DDEAUTO c:\\x</w:instrText>'}), "a.docx")
    assert exc.value.code == "office_external"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/embeddings/oleObject1.bin": b"\x00"}), "a.docx")
    assert exc.value.code == "office_external"


def test_an_office_file_that_inflates_past_the_cap_is_refused_before_it_is_trusted(monkeypatch):
    monkeypatch.setattr(guard, "OFFICE_INFLATE_MAX", 1000)
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/media/big.bin": b"\x00" * 5000}), "a.docx")
    assert exc.value.code == "office_zip_bomb"


def test_pdf_passes_and_active_content_is_refused():
    assert guard.check(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n", "a.pdf")["kind"] == "PDF"
    for bad in (b"%PDF-1.4\n/JavaScript (x)\n%%EOF", b"%PDF-1.4\n/Launch\n%%EOF", b"%PDF-1.4\n/EmbeddedFile\n%%EOF"):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.pdf")
        assert exc.value.code == "pdf_active_content"


def test_size_and_emptiness_are_refused_first(monkeypatch):
    from app.config import settings
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"", "a.pdf")
    assert exc.value.code == "empty"
    monkeypatch.setattr(settings, "attachment_max_bytes", 10)
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png(), "a.png")
    assert exc.value.code == "too_large"


def test_a_type_not_on_the_list_is_refused_by_name():
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"MZ\x90\x00", "tool.exe")
    assert exc.value.code == "type_not_allowed"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attachments_guard.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the schema, the config and the guard**

Append to `backend/app/schema.sql` (inside the `records` section):

```sql
-- Feedback Round 1 / WP4 (design F7): evidence files on a contact or a note. Bytes
-- live here, never on disk; INFECTED is never a stored state — such a file is refused
-- at upload. attached_to is "contact:<uid>" | "note:<uid>" | NULL while pending.
CREATE TABLE IF NOT EXISTS records.attachment (
    uid           text        PRIMARY KEY,
    sha256        text        NOT NULL,
    kind          text        NOT NULL CHECK (kind IN ('PNG','SVG','CSV','XLSX','DOCX','PDF')),
    content_type  text        NOT NULL,
    size          int         NOT NULL,
    filename      text        NOT NULL,
    uploaded_by   text        NOT NULL,
    uploaded_at   timestamptz NOT NULL DEFAULT now(),
    scan_state    text        NOT NULL CHECK (scan_state IN ('CLEAN','RULES_ONLY')),
    scan_by       text        NOT NULL,
    attached_to   text,
    deleted_at    timestamptz,
    deleted_by    text,
    bytes         bytea       NOT NULL
);
CREATE INDEX IF NOT EXISTS attachment_target_idx ON records.attachment (attached_to) WHERE deleted_at IS NULL;
```

`backend/app/config.py` in `class Settings`:

```python
    # Feedback Round 1 / WP4, design F7: per file and per note. Chosen, not ruled.
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachments_per_note: int = 5
```

```python
# backend/app/attachments/guard.py
"""The file guard. A file is stored only after every rule for its type passes.

Design F8: format rules here, standard library only; a virus scanner is a separate
port (scanner.py) that this module never assumes. Each refusal names the rule so the
officer can fix the file rather than guess.
"""
import csv
import hashlib
import io
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

from ..config import settings

CONTENT_TYPES = {"PNG": "image/png", "SVG": "image/svg+xml", "CSV": "text/csv",
                 "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "PDF": "application/pdf"}
EXTENSIONS = {"png": "PNG", "svg": "SVG", "csv": "CSV", "xlsx": "XLSX", "docx": "DOCX", "pdf": "PDF"}
OFFICE_INFLATE_MAX = 50 * 1024 * 1024
OFFICE_ENTRIES_MAX = 2000

_SVG_BAD_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "use"}
_PDF_BAD = re.compile(rb"/(JavaScript|JS|Launch|AA|OpenAction|EmbeddedFile|RichMedia|XFA)\b")
_OFFICE_MACRO = re.compile(r"(^|/)vbaProject\.bin$|macroEnabled", re.IGNORECASE)
_OFFICE_EXTERNAL = re.compile(r"(^|/)(oleObject\d*\.bin|externalLink\d*\.xml)$", re.IGNORECASE)
_DDE = re.compile(r"\bDDE(AUTO)?\b")


class Refused(Exception):
    def __init__(self, code, detail, detail_th, rule=None):
        super().__init__(detail)
        self.code, self.detail, self.detail_th, self.rule = code, detail, detail_th, rule or code


def _sniff(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if raw.startswith(b"%PDF-"):
        return "PDF"
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
        if "[Content_Types].xml" in names:
            if any(n.startswith("xl/") for n in names):
                return "XLSX"
            if any(n.startswith("word/") for n in names):
                return "DOCX"
        return None
    head = raw[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<") and b"<svg" in raw[:65536].lower():
        return "SVG"
    for enc in ("utf-8", "tis-620"):
        try:
            raw.decode(enc)
            return "CSV"
        except UnicodeDecodeError:
            continue
    return None


def _check_png(raw):
    pos, seen_end = 8, False
    while pos + 8 <= len(raw):
        length, kind = struct.unpack(">I", raw[pos:pos + 4])[0], raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        crc = raw[pos + 8 + length:pos + 12 + length]
        if len(data) != length or len(crc) != 4:
            raise Refused("png_corrupt", "a PNG chunk is truncated", "ไฟล์ PNG ไม่สมบูรณ์ (ข้อมูลขาด)")
        if struct.unpack(">I", crc)[0] != (zlib.crc32(kind + data) & 0xFFFFFFFF):
            raise Refused("png_corrupt", "a PNG chunk fails its CRC", "ไฟล์ PNG เสียหาย (CRC ไม่ตรง)")
        pos += 12 + length
        if kind == b"IEND":
            seen_end = True
            break
    if not seen_end or pos != len(raw):
        raise Refused("png_corrupt", "the PNG does not end at IEND", "ไฟล์ PNG มีข้อมูลเกินท้ายไฟล์หรือไม่มี IEND")


def _check_svg(raw):
    text = raw.decode("utf-8", errors="replace")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise Refused("svg_active_content", "SVG carries a DOCTYPE or an entity", "ไฟล์ SVG มี DOCTYPE/ENTITY ซึ่งไม่อนุญาต")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise Refused("svg_active_content", "SVG is not well-formed XML: %s" % exc, "ไฟล์ SVG ไม่ใช่ XML ที่ถูกต้อง")
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag in _SVG_BAD_TAGS:
            raise Refused("svg_active_content", "SVG carries <%s>" % tag, "ไฟล์ SVG มีแท็ก <%s> ซึ่งไม่อนุญาต" % tag)
        for name, value in el.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            v = (value or "").strip().lower()
            if local.startswith("on"):
                raise Refused("svg_active_content", "SVG carries an event handler %s" % local, "ไฟล์ SVG มี event handler (%s)" % local)
            if local in ("href", "xlink:href", "src") and (v.startswith("javascript:") or v.startswith("http:") or v.startswith("https:") or v.startswith("data:")):
                raise Refused("svg_active_content", "SVG references %s" % v[:40], "ไฟล์ SVG อ้างอิงลิงก์ภายนอกหรือสคริปต์")


def _check_csv(raw):
    text = None
    for enc in ("utf-8-sig", "tis-620"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    for r, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        for c, cell in enumerate(row):
            v = cell.lstrip(" \t\r\n")
            if v[:1] in ("=", "+", "-", "@") and len(v) > 1 and not re.match(r"^[-+]?\d", v):
                col = chr(ord("A") + c) if c < 26 else "col%d" % (c + 1)
                raise Refused("csv_formula_cell", "cell %s%d starts with %r (spreadsheet formula)" % (col, r, v[:1]),
                              "เซลล์ %s%d ขึ้นต้นด้วย %s ซึ่งโปรแกรมตารางจะตีความเป็นสูตร" % (col, r, v[:1]))


def _check_office(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        infos = zf.infolist()
        if len(infos) > OFFICE_ENTRIES_MAX:
            raise Refused("office_zip_bomb", "%d zip entries" % len(infos), "ไฟล์มีรายการภายในมากผิดปกติ")
        total = sum(i.file_size for i in infos)
        if total > OFFICE_INFLATE_MAX:
            raise Refused("office_zip_bomb", "inflates to %d bytes" % total, "ไฟล์ขยายตัวใหญ่ผิดปกติ")
        for info in infos:
            if _OFFICE_MACRO.search(info.filename):
                raise Refused("office_macro", "carries %s" % info.filename, "ไฟล์มีมาโคร (%s) ซึ่งไม่อนุญาต" % info.filename)
            if _OFFICE_EXTERNAL.search(info.filename):
                raise Refused("office_external", "carries %s" % info.filename, "ไฟล์มีอ็อบเจกต์ฝังหรือลิงก์ภายนอก (%s)" % info.filename)
        ct = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
        if "macroEnabled" in ct:
            raise Refused("office_macro", "macro-enabled content type", "ไฟล์เป็นชนิดเปิดใช้มาโคร")
        for info in infos:
            if info.filename.endswith(".xml") and info.file_size < 5 * 1024 * 1024:
                body = zf.read(info.filename).decode("utf-8", errors="replace")
                if _DDE.search(body):
                    raise Refused("office_external", "DDE field in %s" % info.filename, "ไฟล์มีฟิลด์ DDE (%s)" % info.filename)


def _check_pdf(raw):
    if b"%%EOF" not in raw[-2048:]:
        raise Refused("pdf_active_content", "no %%EOF trailer", "ไฟล์ PDF ไม่มีส่วนท้าย (%%EOF)")
    m = _PDF_BAD.search(raw)
    if m:
        raise Refused("pdf_active_content", "PDF carries %s" % m.group(0).decode(), "ไฟล์ PDF มี %s ซึ่งไม่อนุญาต" % m.group(0).decode())


CHECKS = {"PNG": _check_png, "SVG": _check_svg, "CSV": _check_csv, "XLSX": _check_office, "DOCX": _check_office, "PDF": _check_pdf}


def check(raw, filename):
    if not raw:
        raise Refused("empty", "the file is empty", "ไฟล์ว่าง")
    if len(raw) > settings.attachment_max_bytes:
        raise Refused("too_large", "%d bytes; the cap is %d" % (len(raw), settings.attachment_max_bytes),
                      "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024)))
    clean = re.sub(r"[^\w.\- ]", "", Path(filename or "").name)[:120] or "file"
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    kind = _sniff(raw)
    if kind is None or ext not in EXTENSIONS:
        raise Refused("type_not_allowed", "only png, svg, csv, xlsx, docx, pdf are accepted",
                      "รับเฉพาะไฟล์ png, svg, csv, xlsx, docx, pdf")
    if EXTENSIONS[ext] != kind:
        raise Refused("extension_mismatch", "named .%s but the bytes are %s" % (ext, kind),
                      "นามสกุลไฟล์ .%s ไม่ตรงกับเนื้อไฟล์ (%s)" % (ext, kind))
    CHECKS[kind](raw)
    return {"kind": kind, "content_type": CONTENT_TYPES[kind], "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "filename": clean}
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_attachments_guard.py -v`
Expected: PASS — 9 tests. (`tis-620` is in Python's codec table; a CSV that is neither UTF-8 nor TIS-620 is `type_not_allowed`, which is the honest answer.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schema.sql backend/app/config.py backend/app/attachments/__init__.py backend/app/attachments/guard.py backend/tests/test_attachments_guard.py
git commit -m "feat(attachments): the file guard — six types, each checked by its own rules, refusals named"
```

---

### Task 21: The store and the scanner port — `attachments/store.py`, `attachments/scanner.py`

**Files:**
- Create: `backend/app/attachments/store.py`, `backend/app/attachments/scanner.py`
- Test: `backend/tests/test_attachments_store.py` (create)

**Interfaces:**
- Produces:
  - `scanner.scan(raw) -> {"state": "CLEAN"|"RULES_ONLY", "by": "clamd"|"rules", "note_th": str}`; raises `scanner.Infected(signature)` and `scanner.ScannerUnavailable(detail)`. Reads `CLAMAV_HOST` / `CLAMAV_PORT` (default 3310) through `integrations.env`.
  - `store.put(meta, raw, uploaded_by, scan) -> record` (record = the table row minus `bytes`, plus `durable: bool`); `store.get(uid) -> (record, bytes) | None`; `store.attach(uid, target) -> record`; `store.delete(uid, by) -> record | None`; `store.list_for(target) -> [record]`. Postgres when `db.configured()`, else a process dict with `durable: False` and `note_th` "ไม่มีฐานข้อมูล — ไฟล์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท".

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_attachments_store.py
import socket
import threading

import pytest
from sqlalchemy import text

from app import db, migrate
from app.attachments import scanner, store

META = {"kind": "PDF", "content_type": "application/pdf", "sha256": "ab" * 32, "size": 20, "filename": "a.pdf"}
CLEAN = {"state": "RULES_ONLY", "by": "rules", "note_th": "x"}


def _clamd(reply):
    """A one-shot fake clamd speaking INSTREAM."""
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    got = {}

    def serve():
        conn, _ = srv.accept()
        data = b""
        while b"\x00\x00\x00\x00" not in data[data.find(b"\x00") + 1:]:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        got["data"] = data
        conn.sendall(reply); conn.close(); srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return port, got


def test_without_clamav_the_scan_is_rules_only_and_says_so(monkeypatch):
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: d)
    out = scanner.scan(b"%PDF-1.4")
    assert out == {"state": "RULES_ONLY", "by": "rules", "note_th": scanner.RULES_ONLY_TH}


def test_a_clean_clamd_answer_is_clean_and_the_stream_was_framed(monkeypatch):
    port, got = _clamd(b"stream: OK\x00")
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": str(port)}.get(k, d))
    assert scanner.scan(b"%PDF-1.4")["state"] == "CLEAN"
    assert got["data"].startswith(b"zINSTREAM\x00") and got["data"].endswith(b"\x00\x00\x00\x00")


def test_an_infected_answer_raises_with_the_signature(monkeypatch):
    port, _ = _clamd(b"stream: Eicar-Test-Signature FOUND\x00")
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": str(port)}.get(k, d))
    with pytest.raises(scanner.Infected) as exc:
        scanner.scan(b"x")
    assert "Eicar" in exc.value.signature


def test_a_configured_but_unreachable_scanner_refuses_rather_than_passing(monkeypatch):
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": "1"}.get(k, d))
    with pytest.raises(scanner.ScannerUnavailable):
        scanner.scan(b"x")


def test_the_memory_store_works_without_a_database_and_says_it_is_not_durable(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    store.reset()
    rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
    assert rec["uid"].startswith("att-") and rec["durable"] is False and "bytes" not in rec
    got, raw = store.get(rec["uid"])
    assert raw == b"%PDF-1.4 twenty bytes" and got["scan_state"] == "RULES_ONLY"
    assert store.attach(rec["uid"], "contact:ct-1")["attached_to"] == "contact:ct-1"
    assert [r["uid"] for r in store.list_for("contact:ct-1")] == [rec["uid"]]
    assert store.delete(rec["uid"], "nantapol")["deleted_by"] == "nantapol"
    assert store.get(rec["uid"]) is None


def test_the_postgres_store_round_trips_bytes_and_is_durable(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
    assert rec["durable"] is True
    _, raw = store.get(rec["uid"])
    assert raw == b"%PDF-1.4 twenty bytes"
    pg_conn.execute(text("delete from records.attachment"))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attachments_store.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write the scanner and the store**

```python
# backend/app/attachments/scanner.py
"""The scanner port (design F8). ClamAV's clamd over TCP (INSTREAM) when configured;
otherwise the honest label RULES_ONLY. Configured-but-unreachable REFUSES the upload —
a scanner that silently passes when it is down is the failure mode this exists to end.
"""
import socket
import struct

from ..integrations import env as _env

RULES_ONLY_TH = "ตรวจตามกฎรูปแบบไฟล์แล้ว ยังไม่ผ่านโปรแกรมสแกนไวรัส (ยังไม่ตั้งค่า ClamAV)"
CLEAN_TH = "ผ่านการสแกนไวรัส (ClamAV)"
CHUNK = 64 * 1024


class Infected(Exception):
    def __init__(self, signature):
        super().__init__(signature)
        self.signature = signature


class ScannerUnavailable(Exception):
    pass


def configured():
    return bool(_env("CLAMAV_HOST"))


def scan(raw):
    host = _env("CLAMAV_HOST")
    if not host:
        return {"state": "RULES_ONLY", "by": "rules", "note_th": RULES_ONLY_TH}
    port = int(_env("CLAMAV_PORT", "3310"))
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(b"zINSTREAM\x00")
            for i in range(0, len(raw), CHUNK):
                piece = raw[i:i + CHUNK]
                sock.sendall(struct.pack(">I", len(piece)) + piece)
            sock.sendall(struct.pack(">I", 0))
            answer = b""
            while not answer.endswith(b"\x00"):
                part = sock.recv(4096)
                if not part:
                    break
                answer += part
    except (OSError, socket.timeout) as exc:
        raise ScannerUnavailable("clamd at %s:%s: %s" % (host, port, exc.__class__.__name__))
    text = answer.rstrip(b"\x00").decode("utf-8", errors="replace")
    if text.endswith("OK"):
        return {"state": "CLEAN", "by": "clamd", "note_th": CLEAN_TH}
    if text.endswith("FOUND"):
        raise Infected(text.split(":", 1)[-1].replace("FOUND", "").strip())
    raise ScannerUnavailable("clamd answered %r" % text[:80])
```

```python
# backend/app/attachments/store.py
"""Where attachment bytes live: records.attachment when a database is configured,
a process dict labelled not-durable when it is not (the same three-state seam db.py
states). Bytes never touch disk and never appear in a log line.
"""
import uuid
from datetime import datetime

from sqlalchemy import text

from .. import db

NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — ไฟล์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
COLUMNS = ("uid", "sha256", "kind", "content_type", "size", "filename", "uploaded_by", "uploaded_at",
           "scan_state", "scan_by", "attached_to", "deleted_at", "deleted_by")

_MEMORY = {}


def reset():
    _MEMORY.clear()


def _uid():
    return "att-" + uuid.uuid4().hex[:12]


def _public(row, durable):
    rec = {k: row.get(k) for k in COLUMNS}
    for k in ("uploaded_at", "deleted_at"):
        if hasattr(rec.get(k), "isoformat"):
            rec[k] = rec[k].isoformat()
    rec["durable"] = durable
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
    return rec


def put(meta, raw, uploaded_by, scan):
    row = {"uid": _uid(), "sha256": meta["sha256"], "kind": meta["kind"], "content_type": meta["content_type"],
           "size": meta["size"], "filename": meta["filename"], "uploaded_by": uploaded_by,
           "uploaded_at": datetime.utcnow(), "scan_state": scan["state"], "scan_by": scan["by"],
           "attached_to": None, "deleted_at": None, "deleted_by": None}
    if not db.configured():
        _MEMORY[row["uid"]] = dict(row, bytes=raw)
        return _public(row, durable=False)
    conn = db.connect()
    try:
        with conn.begin():
            conn.execute(text(
                "insert into records.attachment (uid, sha256, kind, content_type, size, filename, uploaded_by, "
                "scan_state, scan_by, bytes) values (:uid, :sha256, :kind, :content_type, :size, :filename, "
                ":uploaded_by, :scan_state, :scan_by, :bytes)"), dict(row, bytes=raw))
    finally:
        conn.close()
    return _public(row, durable=True)


def get(uid):
    if not db.configured():
        row = _MEMORY.get(uid)
        return (None if row is None or row["deleted_at"] else (_public(row, False), row["bytes"]))
    conn = db.connect()
    try:
        row = conn.execute(text("select * from records.attachment where uid = :u and deleted_at is null"),
                           {"u": uid}).mappings().first()
    finally:
        conn.close()
    return (None if row is None else (_public(dict(row), True), bytes(row["bytes"])))


def attach(uid, target):
    if not db.configured():
        row = _MEMORY[uid]
        row["attached_to"] = target
        return _public(row, False)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text("update records.attachment set attached_to = :t where uid = :u and deleted_at is null "
                                    "returning " + ", ".join(COLUMNS)), {"t": target, "u": uid}).mappings().first()
    finally:
        conn.close()
    return _public(dict(row), True) if row else None


def delete(uid, by):
    if not db.configured():
        row = _MEMORY.get(uid)
        if row is None or row["deleted_at"]:
            return None
        row["deleted_at"], row["deleted_by"] = datetime.utcnow(), by
        return _public(row, False)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text("update records.attachment set deleted_at = now(), deleted_by = :b "
                                    "where uid = :u and deleted_at is null returning " + ", ".join(COLUMNS)),
                               {"b": by, "u": uid}).mappings().first()
    finally:
        conn.close()
    return _public(dict(row), True) if row else None


def list_for(target):
    if not db.configured():
        return [_public(r, False) for r in _MEMORY.values() if r["attached_to"] == target and not r["deleted_at"]]
    conn = db.connect()
    try:
        rows = conn.execute(text("select " + ", ".join(COLUMNS) + " from records.attachment where attached_to = :t "
                                 "and deleted_at is null order by uploaded_at"), {"t": target}).mappings().all()
    finally:
        conn.close()
    return [_public(dict(r), True) for r in rows]
```

Add `store.reset()` to `conftest.fresh_app_state` — an ADDED line in the fixture body beside the other `reset()` calls (it edits no assertion).

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_attachments_store.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/attachments/store.py backend/app/attachments/scanner.py backend/tests/test_attachments_store.py backend/tests/conftest.py
git commit -m "feat(attachments): bytes in the records schema, and a scanner port that refuses when it is configured and down"
```

---

### Task 22: The attachment endpoints — `routers/attachments.py`

**Files:**
- Create: `backend/app/routers/attachments.py`
- Modify: `backend/app/main.py` (include the router)
- Test: `backend/tests/test_attachments_router.py` (create)

**Interfaces:**
- Produces:

| Endpoint | Does |
|---|---|
| `POST /v1/attachments` | raw body, `X-Volt-Filename`, optional `X-Volt-Attach-To`; guard → scan → store; 201 `{attachment}`; 422 on a guard refusal (code = the rule), 422 `file_infected`, 503 `scanner_unavailable`; audit `ATTACHMENT_UPLOADED` |
| `POST /v1/attachments/{uid}:download` | the bytes, `Content-Disposition: attachment; filename*=UTF-8''…`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`; audit `ATTACHMENT_DOWNLOADED` (a POST so the action log records it — the same reason the weekly Excel is a POST) |
| `POST /v1/attachments/{uid}:delete` | the uploader, or MANAGER/OWNER; audit `ATTACHMENT_DELETED` |
| `GET /v1/attachments?attached_to=` | the list for one target (metadata only) |

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_attachments_router.py
from fastapi.testclient import TestClient

from app.attachments import scanner
from app.main import app
from tests.test_attachments_guard import _png

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
OTHER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"}
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _upload(raw=None, name="site.png", headers=OFFICER, attach_to=None):
    h = {**headers, "X-Volt-Filename": name, "Content-Type": "application/octet-stream"}
    if attach_to:
        h["X-Volt-Attach-To"] = attach_to
    return client.post("/v1/attachments", content=raw if raw is not None else _png(), headers=h)


def test_a_clean_file_is_stored_and_answers_without_its_bytes():
    r = _upload(attach_to="contact:ct-1")
    assert r.status_code == 201, r.json()
    att = r.json()["attachment"]
    assert att["kind"] == "PNG" and att["scan_state"] == "RULES_ONLY" and "bytes" not in att
    assert att["attached_to"] == "contact:ct-1" and att["durable"] in (True, False)


def test_a_refused_file_names_the_rule_in_thai():
    r = _upload(raw=b"%PDF-1.4\n/JavaScript\n%%EOF", name="a.pdf")
    assert r.status_code == 422
    body = r.json()
    assert body["errors"][0]["code"] == "pdf_active_content" and body["errors"][0]["message_th"]


def test_the_download_is_a_post_with_attachment_disposition_and_nosniff():
    uid = _upload().json()["attachment"]["uid"]
    r = client.post("/v1/attachments/%s:download" % uid, headers=OFFICER)
    assert r.status_code == 200 and r.content == _png()
    assert r.headers["content-type"].startswith("image/png")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_only_the_uploader_or_a_manager_may_delete():
    uid = _upload().json()["attachment"]["uid"]
    assert client.post("/v1/attachments/%s:delete" % uid, headers=OTHER).status_code == 403
    assert client.post("/v1/attachments/%s:delete" % uid, headers=MANAGER).status_code == 200
    assert client.post("/v1/attachments/%s:download" % uid, headers=OFFICER).status_code == 404


def test_an_infected_or_unreachable_scanner_is_never_a_stored_file(monkeypatch):
    monkeypatch.setattr(scanner, "scan", lambda raw: (_ for _ in ()).throw(scanner.Infected("Eicar")))
    r = _upload()
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "file_infected"
    monkeypatch.setattr(scanner, "scan", lambda raw: (_ for _ in ()).throw(scanner.ScannerUnavailable("down")))
    r = _upload()
    assert r.status_code == 503 and r.json()["code"] == "scanner_unavailable"


def test_the_list_for_a_target_carries_metadata_only():
    _upload(attach_to="note:ev-9")
    r = client.get("/v1/attachments", params={"attached_to": "note:ev-9"}, headers=OFFICER)
    assert r.status_code == 200 and r.json()["attachments"][0]["filename"] == "site.png"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_attachments_router.py -v`
Expected: FAIL — 404s.

- [ ] **Step 3: Write the router**

```python
# backend/app/routers/attachments.py
"""Evidence files on a contact or a note (vault note 10 §3 WP4)."""
from urllib.parse import quote

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response

from .. import audit, errors
from ..attachments import guard, scanner, store
from ..config import settings
from ..officers import sign

router = APIRouter()


async def _body(request):
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.attachment_max_bytes:
            raise errors.validation_failed([{"pointer": "/file", "code": "too_large",
                                             "message": "the stream exceeded the attachment cap",
                                             "message_th": "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024))}])
        chunks.append(chunk)
    return b"".join(chunks)


def _who(body, officer, role):
    return sign(body or {}, officer, role)


@router.post("/v1/attachments", status_code=201)
async def upload(request: Request, x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None),
                 x_volt_filename: str = Header(default=None), x_volt_attach_to: str = Header(default=None)):
    raw = await _body(request)
    try:
        meta = guard.check(raw, x_volt_filename)
    except guard.Refused as exc:
        raise errors.validation_failed([{"pointer": "/file", "code": exc.code, "message": exc.detail,
                                         "message_th": exc.detail_th, "rule": exc.rule}])
    try:
        scan = scanner.scan(raw)
    except scanner.Infected as exc:
        raise errors.validation_failed([{"pointer": "/file", "code": "file_infected",
                                         "message": "the scanner found %s" % exc.signature,
                                         "message_th": "โปรแกรมสแกนพบไวรัส (%s) — ไฟล์ไม่ถูกเก็บ" % exc.signature}])
    except scanner.ScannerUnavailable as exc:
        raise errors.Problem(code="scanner_unavailable", status=503, title="Virus scanner unavailable",
                             detail=str(exc), message_th="โปรแกรมสแกนไวรัสตั้งค่าไว้แต่ติดต่อไม่ได้ — ไม่รับไฟล์จนกว่าจะกลับมา",
                             error_id="DEBT-ATT-0503")
    by = _who(None, x_volt_officer, x_volt_role)
    record = store.put(meta, raw, by, scan)
    if x_volt_attach_to:
        record = store.attach(record["uid"], x_volt_attach_to.strip()[:80]) or record
    audit.describe(act="ATTACHMENT_UPLOADED", subject=("attachment", record["uid"]),
                   detail={"kind": meta["kind"], "size": meta["size"], "sha256": meta["sha256"],
                           "scan": scan["state"], "attached_to": record.get("attached_to")})
    return {"attachment": record}


@router.post("/v1/attachments/{uid}:download")
def download(uid: str):
    found = store.get(uid)
    if found is None:
        raise errors.not_found("attachment")
    record, raw = found
    audit.describe(act="ATTACHMENT_DOWNLOADED", subject=("attachment", uid), detail={"filename": record["filename"]})
    return Response(content=raw, media_type=record["content_type"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(record["filename"]),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, no-store",
    })


@router.post("/v1/attachments/{uid}:delete")
def delete(uid: str, x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    found = store.get(uid)
    if found is None:
        raise errors.not_found("attachment")
    record = found[0]
    by = _who(None, x_volt_officer, x_volt_role)
    if record["uploaded_by"] != by and (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Not yours to delete",
                             detail="only the uploader or a Manager may delete an attachment",
                             message_th="ลบได้เฉพาะผู้อัปโหลดหรือผู้จัดการ", error_id="DEBT-IAM-0403")
    gone = store.delete(uid, by)
    audit.describe(act="ATTACHMENT_DELETED", subject=("attachment", uid), detail={"filename": record["filename"]})
    return {"attachment": gone}


@router.get("/v1/attachments")
def list_attachments(attached_to: str = Query(...)):
    return {"attachments": store.list_for(attached_to)}
```

Read `officers.sign`'s signature (`sign(body, officer_header, role_header, fallback="officer")`) and match it; if it returns a tuple, take the officer element. Include the router in `main.py` beside the others.

- [ ] **Step 4: Run the tests and the audit check**

Run: `cd backend && python -m pytest tests/test_attachments_router.py -v && python -c "from app import audit; print(audit.is_logged('POST','/v1/attachments'), audit.is_logged('POST','/v1/attachments/{uid}:download'))"`
Expected: PASS; `True True`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/attachments.py backend/app/main.py backend/tests/test_attachments_router.py
git commit -m "feat(api): upload, download and delete an evidence file — guarded, scanned or labelled, and logged"
```

---

### Task 23: Notes on a contact and on the case — `cases.py`, two routes

**Files:**
- Modify: `backend/app/cases.py` (`log_contact` accepts `notes`; new `add_contact_note`, `add_case_note`)
- Modify: `backend/app/routers/today.py` (two routes beside `log_case_contact`)
- Test: `backend/tests/test_contact_notes.py` (create)

**Interfaces:**
- Consumes: `store.attach`, `store.list_for` (Task 21).
- Produces:
  - `log_contact(state, case, fields, by)` also reads `fields["notes"] = [{"text", "attachment_uids"}]`; the row gains `notes: [{"uid", "text", "by", "at", "attachments": [records]}]`; the first note also fills the legacy `note` field when `note` is absent.
  - `cases.add_contact_note(state, contact_uid, text, by, attachment_uids=()) -> note`
  - `cases.add_case_note(state, case, text, by, attachment_uids=()) -> event` — an event `{"kind": "NOTE_ADDED", "uid", "case_uid", "text", "by", "on", "attachments"}`; never a contact, never counted.
  - `POST /v1/contacts/{uid}/notes` (case-side `ct-…` uid) and `POST /v1/cases/by-customer/{customer_uid}/notes`, body `{"text", "attachment_uids", "by"}`; 422 `note_text_required`; 422 `too_many_attachments` past `settings.attachments_per_note`; audit `NOTE_ADDED`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_contact_notes.py
"""More than one note per contact, and a note that is not a contact at all."""
from fastapi.testclient import TestClient

from app.main import app
from tests.test_attachments_guard import _png

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def _late_customer():
    return next(i for i in client.get("/v1/today", headers=OFFICER).json()["items"]
                if i["case"]["payment_status"] == "LATE" and i["contact_lock"]["state"] == "OPEN")["customer"]["uid"]


def _attachment():
    return client.post("/v1/attachments", content=_png(), headers={**OFFICER, "X-Volt-Filename": "slip.png",
                                                                     "Content-Type": "application/octet-stream"}).json()["attachment"]["uid"]


def test_a_contact_may_carry_several_notes_each_with_its_files():
    uid = _late_customer()
    a1, a2 = _attachment(), _attachment()
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL", "next_action_on": "2026-10-24",
        "notes": [{"text": "ลูกค้าแจ้งว่าจะโอนพรุ่งนี้", "attachment_uids": [a1]}, {"text": "ส่งลิงก์แล้ว", "attachment_uids": [a2]}]})
    assert r.status_code == 201, r.json()
    row = r.json()["contact"]
    assert [n["text"] for n in row["notes"]] == ["ลูกค้าแจ้งว่าจะโอนพรุ่งนี้", "ส่งลิงก์แล้ว"]
    assert row["note"] == "ลูกค้าแจ้งว่าจะโอนพรุ่งนี้"
    assert row["notes"][0]["attachments"][0]["uid"] == a1 and row["notes"][0]["attachments"][0]["attached_to"] == "contact:%s" % row["uid"]


def test_a_note_can_be_added_to_a_saved_contact_later():
    uid = _late_customer()
    row = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL", "next_action_on": "2026-10-24"}).json()["contact"]
    r = client.post("/v1/contacts/%s/notes" % row["uid"], headers=OFFICER, json={"text": "เพิ่มเติม"})
    assert r.status_code == 201 and r.json()["note"]["text"] == "เพิ่มเติม"
    detail = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert [n["text"] for n in next(c for c in detail["contact_log"] if c["uid"] == row["uid"])["notes"]] == ["เพิ่มเติม"]


def test_a_case_note_is_an_event_not_a_contact_and_spends_no_slot():
    uid = _late_customer()
    before = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    r = client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER, json={"text": "บันทึกเฉย ๆ"})
    assert r.status_code == 201 and r.json()["event"]["kind"] == "NOTE_ADDED"
    after = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert len(after["contact_log"]) == len(before["contact_log"])
    assert after["work_item"]["contact_lock"]["state"] == "OPEN"
    assert any(e["kind"] == "NOTE_ADDED" and e["text"] == "บันทึกเฉย ๆ" for e in after["events"])


def test_an_empty_note_and_too_many_files_are_refused():
    uid = _late_customer()
    assert client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER, json={"text": "  "}).status_code == 422
    r = client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER,
                    json={"text": "x", "attachment_uids": ["a"] * 6})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "too_many_attachments"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_contact_notes.py -v`
Expected: FAIL — `notes` missing from the row; 404 on the note routes.

- [ ] **Step 3: Implement**

`backend/app/cases.py`:

```python
def _note_record(state, text_value, by, attachment_uids, target):
    from .attachments import store
    note = {"uid": state.uid("nt"), "text": text_value.strip(), "by": by, "at": clock.stamp(), "attachments": []}
    for att_uid in attachment_uids or ():
        rec = store.attach(att_uid, target)
        if rec:
            note["attachments"].append(rec)
    return note


def _check_note(text_value, attachment_uids):
    if not text_value or not str(text_value).strip():
        raise CaseError("note_text_required", "A note needs text", message_th="ต้องพิมพ์ข้อความในบันทึก")
    if len(attachment_uids or ()) > settings.attachments_per_note:
        raise CaseError("too_many_attachments", "at most %d files per note" % settings.attachments_per_note,
                        message_th="แนบได้ไม่เกิน %d ไฟล์ต่อบันทึก" % settings.attachments_per_note)


def add_contact_note(state, contact_uid, text_value, by, attachment_uids=()):
    row = next((r for r in state.contact_log if r["uid"] == contact_uid), None)
    if row is None:
        raise CaseError("not_found", "no contact %s" % contact_uid, message_th="ไม่พบการติดต่อนี้")
    _check_note(text_value, attachment_uids)
    note = _note_record(state, text_value, by, attachment_uids, "contact:%s" % contact_uid)
    row.setdefault("notes", []).append(note)
    if not row.get("note"):
        row["note"] = note["text"]
    from . import audit
    audit.describe(act="NOTE_ADDED", subject=("customer", row["customer_uid"]),
                   detail={"contact_uid": contact_uid, "attachments": len(note["attachments"])})
    return note


def add_case_note(state, case, text_value, by, attachment_uids=()):
    _check_note(text_value, attachment_uids)
    uid = state.uid("ev")
    note = _note_record(state, text_value, by, attachment_uids, "note:%s" % uid)
    event = {"kind": "NOTE_ADDED", "uid": uid, "case_uid": case["uid"], "text": note["text"], "by": by,
             "on": str(settings.business_date), "at": note["at"], "attachments": note["attachments"]}
    state.events.append(event)
    from . import audit
    audit.describe(act="NOTE_ADDED", subject=("customer", case["customer_uid"]),
                   detail={"attachments": len(note["attachments"])})
    return event
```

In `log_contact`, after `row = _append_contact(state, case, {...})`, add:

```python
    notes = fields.get("notes") or []
    for n in notes:
        _check_note(n.get("text"), n.get("attachment_uids"))
    row["notes"] = [_note_record(state, n["text"], by, n.get("attachment_uids"), "contact:%s" % row["uid"]) for n in notes]
    if row["notes"] and not row.get("note"):
        row["note"] = row["notes"][0]["text"]
```

(Run `_check_note` for every note BEFORE `_append_contact` if the pre-flight rule at the top of `log_contact` is to hold — move the loop up beside the other pre-flight checks.) `_append_contact` gets `entry.setdefault("notes", [])` so older rows carry the key. `problem_from` gains the rows `note_text_required → 422`, `too_many_attachments → 422`, `not_found → 404` if it lacks them.

`backend/app/routers/today.py`, beside `log_case_contact`:

```python
@router.post("/v1/contacts/{uid}/notes", status_code=201)
def add_contact_note(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    try:
        note = cases_domain.add_contact_note(cs, uid, body.get("text"), who(body, x_volt_officer), body.get("attachment_uids") or [])
    except CaseError as exc:
        raise problem_from(exc)
    return {"note": note}


@router.post("/v1/cases/by-customer/{customer_uid}/notes", status_code=201)
def add_case_note(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        event = cases_domain.add_case_note(cs, case, body.get("text"), who(body, x_volt_officer), body.get("attachment_uids") or [])
    except CaseError as exc:
        raise problem_from(exc)
    return {"event": event, "case": case}
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `cd backend && python -m pytest tests/test_contact_notes.py tests/test_cases.py -v && python -m pytest --continue-on-collection-errors`
Expected: PASS at baseline + additions. `test_round4.py:775`'s seven-key septet is untouched (the contact row, not the work item, gained a key). **Paste the count.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/cases.py backend/app/routers/today.py backend/tests/test_contact_notes.py
git commit -m "feat(case): several notes per contact, a note that is not a contact, each with its evidence files"
```

---

### Task 24: The dialog — repeatable notes with files, and the history at the bottom

**Files:**
- Create: `frontend/src/components/AttachmentField.jsx` (+ `.test.jsx`), `frontend/src/components/DrawerHistory.jsx` (+ `.test.jsx`)
- Modify: `frontend/src/api.js` (`uploadAttachment(file, attachTo)`, `downloadAttachment(uid)`, `addContactNote(uid, body)`, `addCaseNote(customerUid, body)`)
- Modify: `frontend/src/components/CaseContactDrawer.jsx` (the note section → repeatable; `notes` in the save body; "add a note" after save; the history section; prop `timeline`)
- Modify: `frontend/src/screens/CustomerCase.jsx:1853` (pass `timeline`), `frontend/src/i18n-today.js` (`cdrawer.notes*`, `att.*`, `cdrawer.history*`), `frontend/src/journey.css`
- Test: `frontend/src/components/CaseContactDrawer.test.jsx` (append)

**Interfaces:**
- Produces: `api.uploadAttachment(file, attachTo?)` (raw body; `X-Volt-Attach-To` when given) → `{attachment}`; `api.downloadAttachment(uid)` → `{blob, filename}` (the `weeklyExport` pattern); `<AttachmentField files onChange max />` (uploads on pick, lists `filename · size · scan label`, removes); `<DrawerHistory rows />` — the case page's `timeline` rows (contacts, events incl. `NOTE_ADDED`, closed issues) newest first in a scroll region with `data-testid="cd-history"`, attachments as download buttons; the drawer's save body carries `notes: [{text, attachment_uids}]`; after a save a "+ เพิ่มบันทึก" form posts `addContactNote`.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/AttachmentField.test.jsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { AttachmentField } from './AttachmentField.jsx'

vi.mock('../api.js', () => ({ api: { uploadAttachment: vi.fn() } }))

describe('AttachmentField', () => {
  beforeEach(() => vi.clearAllMocks())
  it('uploads a picked file at once, lists it with its scan label, and hands the uid up', async () => {
    api.uploadAttachment.mockResolvedValue({ attachment: { uid: 'att-1', filename: 'slip.png', size: 1234, kind: 'PNG', scan_state: 'RULES_ONLY' } })
    const onChange = vi.fn()
    renderIn('th', <AttachmentField files={[]} onChange={onChange} />)
    const input = screen.getByLabelText(/แนบไฟล์/)
    fireEvent.change(input, { target: { files: [new File(['x'], 'slip.png', { type: 'image/png' })] } })
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ uid: 'att-1' })]))
  })
  it('shows a guard refusal verbatim and keeps the list as it was', async () => {
    api.uploadAttachment.mockRejectedValue(Object.assign(new Error('x'), { problem: { errors: [{ code: 'pdf_active_content', message_th: 'ไฟล์ PDF มี /JavaScript ซึ่งไม่อนุญาต' }] } }))
    renderIn('th', <AttachmentField files={[]} onChange={vi.fn()} />)
    fireEvent.change(screen.getByLabelText(/แนบไฟล์/), { target: { files: [new File(['x'], 'a.pdf')] } })
    expect(await screen.findByText(/JavaScript/)).toBeInTheDocument()
  })
  it('labels a rules-only file so nobody mistakes it for a scanned one, and refuses a sixth', () => {
    const five = Array.from({ length: 5 }, (_, i) => ({ uid: `att-${i}`, filename: `f${i}.png`, size: 1, kind: 'PNG', scan_state: 'RULES_ONLY' }))
    renderIn('th', <AttachmentField files={five} onChange={vi.fn()} max={5} />)
    expect(screen.getAllByText(/ยังไม่ผ่านโปรแกรมสแกนไวรัส/)).toHaveLength(5)
    expect(screen.getByLabelText(/แนบไฟล์/)).toBeDisabled()
  })
})
```

```jsx
// frontend/src/components/DrawerHistory.test.jsx
import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'
import { DrawerHistory } from './DrawerHistory.jsx'

vi.mock('../api.js', () => ({ api: { downloadAttachment: vi.fn() } }))

const ROWS = [
  { key: 'c-1', at: '2026-10-22 10:00:00', contact: { uid: 'ct-1', occurred_at: '2026-10-22 10:00:00', officer_uid: 'thip', channel: 'PHONE', result: 'REACHED_ANSWERED', counted: true,
      notes: [{ uid: 'nt-1', text: 'จะโอนพรุ่งนี้', by: 'thip', at: '2026-10-22 10:01:00', attachments: [{ uid: 'att-1', filename: 'slip.png', size: 10, scan_state: 'CLEAN' }] }] } },
  { key: 'e-1', at: '2026-10-21', event: { kind: 'NOTE_ADDED', text: 'บันทึกเฉย ๆ', by: 'noon', on: '2026-10-21', attachments: [] } },
  { key: 'e-2', at: '2026-10-20', event: { kind: 'NEXT_ACTION_SET', action: 'CALL', on: '2026-10-20', by: 'thip' } },
]

describe('DrawerHistory', () => {
  it('draws every row newest first in a scroll region, with notes and their files', () => {
    renderIn('th', <DrawerHistory rows={ROWS} />)
    const region = screen.getByTestId('cd-history')
    expect(region).toHaveAttribute('tabindex', '0')
    const items = within(region).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('จะโอนพรุ่งนี้')
    expect(within(items[0]).getByRole('button', { name: /slip.png/ })).toBeInTheDocument()
    expect(items[1]).toHaveTextContent('บันทึกเฉย ๆ')
  })
  it('says so when there is no history yet', () => {
    renderIn('th', <DrawerHistory rows={[]} />)
    expect(screen.getByTestId('cd-history-empty')).toBeInTheDocument()
  })
})
```

Append to `CaseContactDrawer.test.jsx` (the file's `api` mock gains `uploadAttachment`, `addContactNote`, `downloadAttachment` as additions):

```jsx
it('sends every note with its files on save, then lets another note be added to the saved contact', async () => {
  api.uploadAttachment.mockResolvedValue({ attachment: { uid: 'att-1', filename: 'slip.png', size: 1, kind: 'PNG', scan_state: 'RULES_ONLY' } })
  api.addContactNote.mockResolvedValue({ note: { uid: 'nt-2', text: 'อีกหนึ่ง', attachments: [] } })
  renderIn('th', <Drawer />)
  await screen.findByRole('dialog')
  fireEvent.click(screen.getByLabelText('ติดต่อได้ - รับสาย'))
  fireEvent.change(screen.getAllByLabelText(/บันทึกเพิ่มเติม/)[0], { target: { value: 'โน้ตแรก' } })
  fireEvent.click(screen.getByRole('button', { name: '+ เพิ่มบันทึก' }))
  fireEvent.change(screen.getAllByLabelText(/บันทึกเพิ่มเติม/)[1], { target: { value: 'โน้ตสอง' } })
  fireEvent.change(screen.getAllByLabelText(/แนบไฟล์/)[1], { target: { files: [new File(['x'], 'slip.png', { type: 'image/png' })] } })
  await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalled())
  fireEvent.change(screen.getByLabelText(/งานถัดไป/), { target: { value: 'CALL' } })
  fireEvent.change(screen.getByLabelText(/วันที่/), { target: { value: '2026-10-24' } })
  fireEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
  await waitFor(() => expect(api.logCaseContact).toHaveBeenCalledWith('cu-1', expect.objectContaining({
    notes: [{ text: 'โน้ตแรก', attachment_uids: [] }, { text: 'โน้ตสอง', attachment_uids: ['att-1'] }] })))
  fireEvent.change(await screen.findByLabelText(/เพิ่มบันทึกในการติดต่อนี้/), { target: { value: 'อีกหนึ่ง' } })
  fireEvent.click(screen.getByRole('button', { name: 'บันทึกโน้ต' }))
  await waitFor(() => expect(api.addContactNote).toHaveBeenCalledWith('ct-1', { text: 'อีกหนึ่ง', attachment_uids: [] }))
})

it('shows the history the case page hands in, at the bottom, scrollable', async () => {
  renderIn('th', <Drawer timeline={[{ key: 'e-1', at: '2026-10-21', event: { kind: 'NOTE_ADDED', text: 'เก่า', by: 'noon', on: '2026-10-21', attachments: [] } }]} />)
  const region = await screen.findByTestId('cd-history')
  expect(region).toHaveTextContent('เก่า')
  const dialog = screen.getByRole('dialog')
  expect(dialog.lastElementChild.contains(region)).toBe(true)
})
```

(Read the drawer's existing result-picker and next-action labels in the test file first — the label texts above must be the ones `DICTS` and `i18n-today.js` actually render; copy them from the existing tests in that file.)

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/AttachmentField.test.jsx src/components/DrawerHistory.test.jsx src/components/CaseContactDrawer.test.jsx`
Expected: FAIL — components missing; `notes` absent from the body.

- [ ] **Step 3: Build the pieces**

`api.js`:

```js
  // Feedback Round 1 / WP4 — evidence files and notes.
  uploadAttachment: (file, attachTo) => postRaw('/v1/attachments', file, attachTo ? { 'X-Volt-Attach-To': attachTo } : {}),
  downloadAttachment: async (uid) => {
    const response = await fetch(`${BASE}/v1/attachments/${uid}:download`, { method: 'POST', headers: roleHeaders() })
    if (!response.ok) { const body = await response.json().catch(() => null); throw Object.assign(new Error(uid), { problem: body, status: response.status }) }
    const disposition = response.headers.get('Content-Disposition') || ''
    const m = /filename\*=UTF-8''([^;]+)/.exec(disposition)
    return { blob: await response.blob(), filename: m ? decodeURIComponent(m[1]) : uid }
  },
  addContactNote: (uid, body) => post(`/v1/contacts/${uid}/notes`, body),
  addCaseNote: (customerUid, body) => post(`/v1/cases/by-customer/${customerUid}/notes`, body),
```

(`postRaw` gained `extraHeaders` in Task 17; if Task 17 has not run yet, add the parameter here.)

```jsx
// frontend/src/components/AttachmentField.jsx
import { useId, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../prefs.jsx'
import { fromError } from '../problem.js'

const ACCEPT = '.png,.svg,.csv,.xlsx,.pdf,.docx'

// One file input, uploads on pick so the guard's answer is seen before the officer
// writes another word. `files` are the server's attachment records; the parent owns
// them and sends their uids with the note. A RULES_ONLY file is labelled as such —
// never presented as scanned.
export function AttachmentField({ files = [], onChange, max = 5, attachTo = null }) {
  const t = useT()
  const id = useId()
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  async function onPick(event) {
    const picked = Array.from(event.target.files || [])
    event.target.value = ''
    if (!picked.length) return
    setProblem(null); setBusy(true)
    const next = [...files]
    for (const file of picked.slice(0, Math.max(0, max - files.length))) {
      try {
        const { attachment } = await api.uploadAttachment(file, attachTo)
        next.push(attachment)
      } catch (e) { setProblem(fromError(e)); break }
    }
    setBusy(false)
    onChange(next)
  }
  const full = files.length >= max
  return (
    <div className="att">
      <label htmlFor={id} className="att__label">{t('att.pick')}</label>
      <input id={id} type="file" accept={ACCEPT} multiple disabled={full || busy} onChange={onPick} />
      <p className="cd-hint">{t('att.hint', { max })}</p>
      {files.length > 0 && (
        <ul className="att__list">
          {files.map((f) => (
            <li key={f.uid} className="att__item">
              <span>{f.filename}</span> <span className="td-quiet">{Math.max(1, Math.round(f.size / 1024))} KB</span>{' '}
              <span className={`att__scan att__scan--${f.scan_state}`}>{t(`att.scan.${f.scan_state}`)}</span>
              <button type="button" className="btn btn--sm" onClick={() => onChange(files.filter((x) => x.uid !== f.uid))}>{t('att.remove')}</button>
            </li>
          ))}
        </ul>
      )}
      {problem && <p className="cd-hint cd-hint--required" role="alert">{(problem.errors && problem.errors[0]?.message_th) || problem.message_th || problem.title}</p>}
    </div>
  )
}
```

```jsx
// frontend/src/components/DrawerHistory.jsx
import { api } from '../api.js'
import { useT, usePrefs } from '../prefs.jsx'
import { fmtWhen, codeLabel } from './CaseContactDrawer.jsx'
import { formatDate } from './NextAction.jsx'

// The case's own timeline, inside the dialog, at the bottom, in a scroll region.
// Rows are the case page's `timeline` entries verbatim (contact | event | issueClosed);
// nothing is re-derived here. A file is a download button, never an inline preview.
async function save(uid) {
  const { blob, filename } = await api.downloadAttachment(uid)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function Files({ files, t }) {
  if (!files || !files.length) return null
  return (
    <span className="cd-hist__files">
      {files.map((f) => (
        <button key={f.uid} type="button" className="btn btn--sm" onClick={() => save(f.uid)} title={t(`att.scan.${f.scan_state}`)}>{f.filename}</button>
      ))}
    </span>
  )
}

export function DrawerHistory({ rows = [] }) {
  const t = useT()
  const { lang } = usePrefs()
  return (
    <div className="cd-section cd-hist">
      <p className="cd-eyebrow">{t('cdrawer.history')}</p>
      {rows.length === 0 ? (
        <p className="cd-hint" data-testid="cd-history-empty">{t('cdrawer.historyEmpty')}</p>
      ) : (
        <div className="cd-hist__scroll" data-testid="cd-history" tabIndex={0} role="region" aria-label={t('cdrawer.history')}>
          <ol className="cd-hist__list">
            {rows.map((row) => (
              <li key={row.key} className="cd-hist__row">
                {row.contact ? (
                  <>
                    <span className="td-quiet">{fmtWhen(row.contact.occurred_at)} · {row.contact.officer_uid || '—'}</span>
                    <span>{codeLabel(row.contact.channel, lang, 'channel')} · <strong>{row.contact.result || '—'}</strong>{row.contact.counted ? ` · ${t('case.counted')}` : ''}</span>
                    {(row.contact.notes || []).map((n) => (
                      <span key={n.uid} className="cd-hist__note">{n.text} <Files files={n.attachments} t={t} /></span>
                    ))}
                    {!row.contact.notes?.length && row.contact.note && <span className="cd-hist__note">{row.contact.note}</span>}
                  </>
                ) : row.event ? (
                  <>
                    <span className="td-quiet">{formatDate(row.event.on) || row.event.on || '—'} · {row.event.by || 'SYSTEM'}</span>
                    <span>{row.event.kind === 'NOTE_ADDED' ? row.event.text : t(`case.event.${row.event.kind}`, row.event)}</span>
                    <Files files={row.event.attachments} t={t} />
                  </>
                ) : (
                  <span>{t('case.issueClosedMark')} {row.issueClosed?.summary || row.issueClosed?.uid}</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
```

Check that `case.event.<KIND>` keys exist in `i18n-today.js` for the event kinds the case page already renders (it has a `switch` or a key table for them — reuse whichever it uses rather than a new `case.event.*` table; if the page renders events inline without keys, extract that render into a shared `EventLine` in `DrawerHistory.jsx` and have the page import it — one definition, two callers).

`CaseContactDrawer.jsx`:
- state `notes` = `[{ text: '', files: [] }]` replaces `note`; the section renders one block per note (textarea labelled `t('cdrawer.note')` with an index in the id, an `AttachmentField`), a `+ เพิ่มบันทึก` button (`t('cdrawer.addNote')`) that appends a block, and a remove button on blocks after the first;
- the save body sends `notes: notes.filter((n) => n.text.trim() || n.files.length).map((n) => ({ text: n.text.trim(), attachment_uids: n.files.map((f) => f.uid) }))` and keeps `note: (first note text) || null` for older servers;
- after `logged`, a small form (`cdrawer.addNoteAfter` label "เพิ่มบันทึกในการติดต่อนี้", an `AttachmentField` with `attachTo={`contact:${logged.contact_uid}`}`, button `cdrawer.saveNote` "บันทึกโน้ต") posts `api.addContactNote(logged.contact_uid, { text, attachment_uids })` — so `setLogged` must also keep `contact_uid: second?.contact?.uid`;
- prop `timeline = null`; `const historyRows = timeline || fetchedTimeline` where `fetchedTimeline` is built from Task 19's `fetched` (`contact_log` + `events`, sorted newest first by `occurred_at || on`) — the same three-line merge the case page does, inlined here; `<DrawerHistory rows={historyRows} />` is the **last child** of the `<aside>`;
- `CustomerCase.jsx:1853` passes `timeline={timeline}`.

`i18n-today.js` (EN / TH): `cdrawer.addNote` "+ Add a note" / "+ เพิ่มบันทึก"; `cdrawer.removeNote` "Remove" / "ลบ"; `cdrawer.addNoteAfter` "Add a note to this contact" / "เพิ่มบันทึกในการติดต่อนี้"; `cdrawer.saveNote` "Save note" / "บันทึกโน้ต"; `cdrawer.history` "History" / "ประวัติ"; `cdrawer.historyEmpty` "No history yet" / "ยังไม่มีประวัติ"; `att.pick` "Attach files" / "แนบไฟล์"; `att.hint` "png svg csv xlsx pdf docx · up to 10 MB each · {max} per note · checked before they are kept" / "png svg csv xlsx pdf docx · ไม่เกิน 10 MB ต่อไฟล์ · {max} ไฟล์ต่อบันทึก · ตรวจก่อนเก็บ"; `att.remove` "Remove" / "เอาออก"; `att.scan.CLEAN` "virus-scanned" / "ผ่านสแกนไวรัส"; `att.scan.RULES_ONLY` "checked by format rules, not yet by a virus scanner" / "ตรวจตามกฎรูปแบบไฟล์ ยังไม่ผ่านโปรแกรมสแกนไวรัส".

`journey.css` (tokens only): `.cd-hist__scroll { max-height: 40vh; overflow: auto; border-top: 1px solid var(--line); padding-top: var(--space-2); }`, `.cd-hist__list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }`, `.cd-hist__row { display: grid; gap: 2px; }`, `.att__list { list-style: none; margin: var(--space-2) 0 0; padding: 0; display: grid; gap: var(--space-1); }`, `.att__scan--RULES_ONLY { color: var(--ink-500); }`.

- [ ] **Step 4: Run the four test files, i18n parity, the density census, the suite and the build**

Run: `cd frontend && npx vitest run src/components/AttachmentField.test.jsx src/components/DrawerHistory.test.jsx src/components/CaseContactDrawer.test.jsx src/i18n.test.js src/density.test.jsx && npx vitest run && npx vite build`
Expected: PASS. The dialog is not on the case page's census unless the census opens it (Task 19 recorded which). **Paste the count.** If `CaseContactDrawer.test.jsx` has an existing assertion on the single `#cd-note` textarea, that is a pinned test: stop and price it (F17) rather than edit it — keep `id="cd-note"` on the FIRST note's textarea so the pin holds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/components/AttachmentField.jsx frontend/src/components/AttachmentField.test.jsx frontend/src/components/DrawerHistory.jsx frontend/src/components/DrawerHistory.test.jsx frontend/src/components/CaseContactDrawer.jsx frontend/src/components/CaseContactDrawer.test.jsx frontend/src/screens/CustomerCase.jsx frontend/src/i18n-today.js frontend/src/journey.css
git commit -m "feat(dialog): several notes with checked files, and the case's history at the bottom of the Save-contact dialog"
```

---

### Task 25: Round A closes — the full harness, the counts, the notes

**Files:** none in the product tree; this plan (repo copy) and the vault copies of notes 10 and 11.

- [ ] **Step 1: Run everything on the worktree, with the test database**

Run: `VOLT_TEST_PG_URL="$VOLT_TEST_PG_URL" ./scripts/verify_all.sh`
Expected: EVERYTHING PASSED. Paste backend / frontend / e2e counts beside Task 0's baseline. Every increase is an addition; any pinned test that had to move is listed here with its edit number (35–39) and Arina's yes beside it — or it did not move.

- [ ] **Step 2: Run the real PEAK export through the door once, locally, with `DATABASE_URL` set to `volt_local`**

Run: the upload from the Data sources screen (login on, `owner.test`), then apply. Expected: the receipt reads `7638 invoices · matched ≈ 2,8xx · candidates ≈ 6xx · unmatched ≈ 4,2xx` (the exact numbers go here); one matched customer's case page shows the scorecard with `จากรายงานใบแจ้งหนี้ PEAK ณ 14/09/2026`, paid/open counts, and PEAK-sourced cycles.

- [ ] **Step 3: Write the findings back**

Append a "Round A landed" section to vault note 10 (§9) with: the counts, the measured match rates on the real export, the three answers still open (F-rows Arina has not ruled), and any pin that had to be priced. Update note 00's table row for note 11 from "draft, not started" to "Round A landed <date>".

- [ ] **Step 4: Merge**

Per the shared-branch rule: `git log --oneline -8` on `design-team` first; if it moved, rebase the worktree branch onto it, re-run `verify_all.sh`, then fast-forward `design-team` and tell Arina which commits landed.

---

# Round B — UI (task headers; cut to steps in note 12 after Round A lands and F10–F15 are ruled)

Each header names the files, the interface it produces and the tests it adds. No step is written yet, deliberately: WP7 reads `payment_position` and WP12 reads WP1's receipts, so their code is cut against what Round A actually serves.

| Task | WP | Files | Produces | Tests (added) | Pins to price (F17) |
|---|---|---|---|---|---|
| B1 | WP7 | `screens/Today.jsx`, `App.jsx` (route `/reminders`), `screens/Reminders.jsx` (new, mounts `remindersBlock` verbatim), `Shell.jsx` (rail row under Today), `i18n-today.js` | The reminders block leaves Today's list and board; `/reminders` serves it with the same test ids | `Reminders.test.jsx` | `Today.test.jsx:270-280` (1 test re-targeted) — the only edit |
| B2 | WP7 | `screens/Today.jsx` (tier strip + workload → `FilterBar`), `routers/today.py` (`GET /v1/today` accepts `tier=`, `officer=`, `payment_status=`, `dc_status=`, `product=`, `q=`; refuses unknown values 422), `i18n-today.js` | Today's list and board filter by the seven tiers, the roster (counts in labels — the team-workload data), the two statuses, product and a search box | `Today.filter.test.jsx`, backend `test_today_filters.py` | tier-anchor pins in `Today.test.jsx` / `round4.test.jsx` (13 lines, measured) — keep `data-tier-code` on the filter options to hold as many as possible |
| B3 | WP7 | `screens/Today.jsx`, `screens/Recovery.jsx`, `screens/InvoicePipeline.jsx`, `components/Notice.jsx` (`SystemNotes` fold), `today.css` | One `<details data-testid="system-notes">` per screen holding OD-04, CF1, dial-off, PTP-history and pick-officer lines; children always rendered, `hidden` closes (house rule) so every existing test id stays reachable | `SystemNotes.test.jsx` | `InvoicePipeline.test.jsx:102` (`getByRole('status')`) — keep that notice's role inside the fold: 0 |
| B4 | WP7 | `today-density.test.jsx` (measure only) | Chrome under 112, row under 31, page under 1,662 after B1–B3 | — | none if under; else F17 |
| B5 | WP8 | `screens/CustomerCase.jsx` (header → figures only; `รายละเอียดการคำนวณ` fold beside the history fold; "แก้ไขที่ตั้งค่า" link for OWNER), `MoneyPosition.jsx` (`foldDecided` becomes "render into the bottom fold" via a `slot` prop), `i18n-today.js` | The header holds figures; every derivation moves down; settings values link to WP10's form | `CustomerCase.header.test.jsx` | `density.test.jsx` should fall; `CustomerCase.test.jsx` pins on `mp-note-toggle` / `arrears-hold-toggle` ids — keep the ids in the fold: 0 |
| B6 | WP9 | `schema.sql` (`records.customer_contact`), `cases.py` (`set_phone`), `routers/today.py` (`POST /v1/cases/by-customer/{uid}/phone` reason required, E.164 validated, audit `PHONE_SET`), `routers/journey.py` (`customer.phone_e164` and `phone_on_file` read the override first) | A durable, audited phone per customer; dial buttons come alive where it is set | `test_customer_phone.py` | `test_journey_rebuild.py:63` asserts `"x" in phone_masked` on every row — the masked string is untouched: 0 |
| B7 | WP9 | `screens/CustomerCase.jsx` (copy button, edit form with reason), `CaseContactDrawer.jsx` (shows it), `i18n-today.js` | Copyable, editable phone on the case and in the dialog; the sheet's mask stays beside it | `CustomerCase.phone.test.jsx` | `density.test.jsx` +4 — measured |
| B8 | WP10 | `routers/settings.py` (`changed_by`/`changed_at` per key on `PUT /v1/config`, persisted with the config store), `schema.sql` if the store is Postgres-backed | Every config row says who changed it last and when | `test_settings_changed_by.py` | 0 |
| B9 | WP10 | `screens/Settings.jsx` (sections → forms: label, input with unit, state badge, source line, lock icon, last-changed line), `admin.css` (tokens), `i18n-admin.js` | The settings page from the screenshot, one field per row, grouped | `Settings.form.test.jsx` | `Settings.test.jsx` pins `cfg-<key>`, `cfg-input-<key>`, `cfg-save-<key>`, `cfg-problem-<key>` — keep every id on the new form: 0 |
| B10 | WP10 | `schema.sql` (`records.user_account`), `auth.py` (merge DB rows over the env allow-list; disabled wins), `routers/login.py` (`GET/POST /v1/auth/users`, `POST /v1/auth/users/{id}:disable`, `PUT /v1/auth/me/profile` for one's own display name), `deploy_gcp.sh` nothing | Invite by e-mail + role + officer; a person names themself | `test_auth_users.py` | 0 (login tests use `AUTH_MODE` off unless they set it) |
| B11 | WP10 | `screens/Settings.jsx` (ผู้ใช้ tab), `components/RoleSwitcher.jsx` (display-name field in the identity menu), `i18n-admin.js` | The Users tab and the self-service display name | `Settings.users.test.jsx` | 0 |
| B12 | WP11 | `routers/login.py` (`display_name` on `/v1/auth/me`), `screens/Today.jsx` (title `สวัสดี {name}` + one rotating positive line from `today.hello.*`), `i18n-today.js` | The greeting | `Today.greeting.test.jsx` | `Today.test.jsx` may pin the page title text — measured |
| B13 | WP12 | `reports.py` (`mom`, `paying_customers`, `npl_movement`, `arrears_split`, `status_changes` from `PAYMENT_STATUS_SET`), `weekly_export.py` (the same cells) | The four dashed cards become figures with their definition lines (design F15) | `test_weekly_figures.py` | 0 (additive keys) |
| B14 | WP12 | `components/WeeklyOverview.jsx` (PendingCard → real cards when served; the movements table reads `status_changes`), `i18n-admin.js` | The screenshot, filled | `Reports.weekly.test.jsx` (append) | the staged tests pin "not sent" on the four cards — they are the other session's; price with F18's answer |
| B15 | — | full harness, counts, note 10 §9 | Round B closes | — | — |

# Round C — extras (task headers; cut to steps in note 13)

| Task | WP | Files | Produces | Tests | Pins |
|---|---|---|---|---|---|
| C1 | WP5 | `integrations/peak_reports.py` (new: `list_invoices(since, instance)` behind `PEAK_REPORT_API_BASE_URL`, `PEAK_REPORT_API_TOKEN`; answers `not_configured` / `untested` until an endpoint is verified against PEAK's documentation), `pipelines/peak_service.run_api()`, `routers/peak_pipeline.py` (`{"source": "api"}` door), `PeakReportCard.jsx` (door 2 with its state in words) | The second door, honest about its state; no webhook receiver (design F19) | `test_peak_api_door.py`, `PeakReportCard.test.jsx` (append) | PKD-001's reflection test looks at `integrations/peak.py` only — verify it does not scan the package: 0 |
| C2 | WP6 | `routers/calendar.py` (`GET /v1/calendar?from&to` → next actions, PTP dates, reminder batches, review SLA deadlines, issue deadlines, restructure/settlement/buy-back dates, personal notices), `schema.sql` (`records.notice`), `cases.py` (`notices` CRUD, audit `NOTICE_*`) | One dated list from the stores that already exist, and personal notices | `test_calendar.py` | 0 |
| C3 | WP6 | `screens/Calendar.jsx` (month grid + week list; click → case page or the dialog; drag a next action → `set_next_action` with a reason), `App.jsx` (`/calendar`), `Shell.jsx` (rail row `ปฏิทิน`), `Reminders.jsx` retired into the calendar, `calendar.css` (tokens), `i18n-journey.js` | The calendar (design F16) | `Calendar.test.jsx` | `Reminders.test.jsx` from B1 re-targets: 1 |
| C4 | — | full harness, counts, note 10 §9 | Round C closes | — | — |

---

## Self-review

**Spec coverage (design §3 → tasks).** WP1 door 1 → 2, 5, 8; parser → 2; ladder → 3; link register → 4, 8, 12; landing table and the `peak` block → 1, 4, 6; engine (invoices, receipts, F3) → 7; overview overlay → 9; `payment_position` → 10, 13; case status (F2) → 11; Data sources card, case page source line, book filter → 12, 13, 14; error table → 2 (header, status), 4 (older report), 5 (run death), 8 (422s). WP2 → 15, 16, 17 (and the crm.lead design's §12 items 1–2 close in passing). WP3 → 18, 19. WP4 notes → 23, 24; attachments and the guard table → 20, 21, 22, 24; history at the bottom → 24. WP5 → C1. WP6 → C2, C3. WP7 → B1–B4. WP8 → B5. WP9 → B6, B7. WP10 → B8–B11. WP11 → B12. WP12 → B13, B14. Design §5's test price → Task 0's table and every task's measure step.

**Placeholder scan.** No "TBD", no "add validation", no "similar to Task N" — each task repeats the code its neighbour needs. Two places say "read X first and match it" (`DropZone`'s prop names, `officers.sign`'s return, the drawer's label texts in its own test file): those are instructions to copy the tree's existing names verbatim, not gaps.

**Type consistency.** `peak_report.parse(raw, filename)` → `parsed` dict is what `peak_writer.write(conn, parsed, verdicts, …)` and `peak_service._land(uid, parsed, filename)` take. `peak_match.match(invoices, book, odoo, links)` returns the verdict dicts `peak_writer.write` stores (`verdict`, `rule`, `customer_no`, `candidates`). `peak_writer.invoices_for_book(conn)` → `{customer_no: {report_as_of, run_id, invoices}}` is what `book_source._from_landing` sets as `record["peak"]`, which `book.build` carries as `fixture.sheet`, read by `journey._seed_peak_invoices(state, customer, peak, bd)`, `payment_position.build`, and `cases._peak_says`. `journey.reseed_peak(state, bd)` and `cases.follow_system_for_all()` are called by `routers/peak_pipeline._after_apply()`. `payment_summary.peak_cycles_for(contract_uid, jstate)` returns the triple the router unpacks. `payment_position.build(customer, jstate, business_date)` is called at the four sites with those three arguments. Frontend: `api.peakReport*` / `api.peakLink*` names match the card; `<PaymentOverview summary position compact />` is mounted with those props on the case page and in the drawer; `<PaymentPosition pp compact />` on three screens; `<AttachmentField files onChange max attachTo />` and `<DrawerHistory rows />` in the drawer; the drawer's new props are `paymentSummary`, `paymentPosition`, `timeline`.

**Known risks, named.** Task 8's apply reloads the book for the whole process while other testers' sessions keep their old invoices until they reset — said on the response. Task 13 and Task 18 can meet the density caps; both measure first and have a fallback that costs no test edit. Task 16 may find `test_pipeline_schedule.py` pinning `run_odoo()`'s exact call — the step says stop and price. Task 0's two blockers are Arina's, not the implementer's.
