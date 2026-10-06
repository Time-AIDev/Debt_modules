# PEAK document upload and the payment position — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an officer upload a PEAK invoice or receipt against a customer, and make "has this customer paid, how much, when, and who says so" one legible, server-owned block instead of four scattered components.

**Architecture:** One new server-owned object, `payment_position`, carrying the position **and its provenance** (`source` + `as_of`), served beside the existing `money_position` on the rows that already carry it. One new frontend component renders it on all three screens. The PEAK upload then becomes a *second writer* of a surface already built to show which source last moved it — it stages a run that **proposes** changes and applies nothing until a person applies it, the same posture as `imports.py` and the same reason PEAK writes are `DRAFT_ONLY`.

**Tech Stack:** FastAPI (no new dependencies), React 18 + Vite, vitest, pytest.

**Spec:** embedded — §1 below is the design this plan argues from. Evidence is §0.

## Global Constraints

- **Authority ladder:** Requirements Amendment v2.6 §1 (`briefs/realignment/requirements_amendment_v2_6.html`). Deck v20.0 is **not** a ranked row.
- **REQ-COL-075 / Data Model v2.3 §3:** `payment_status` and `dc_status` are two fields and neither derives the other; a screen that shows one must show both. **`payment_status` keeps its five values and `StatusPair` is not modified by this plan.**
- **`api.js:1-4`:** the client never computes a number the server owns. Every figure in `payment_position` is produced once, server-side, and rendered as served.
- **Decision C3 / PKD-001:** `backend/app/integrations/peak.py` has exactly four public functions — `probe`, `create_draft`, `read_state`, `status`. **This plan adds none.** The upload path never touches that module.
- **Test contract:** green at or above the measured baseline, counts pasted. **A test that must change is escalated to Arina, never edited.** Adding tests is free and is how every task here is paid for.
- **`frontend/src/density.test.jsx`** caps CustomerCase at 76 pre-contact / 112 worked. Any addition to that screen is measured against it **before** the edit, not after (the lesson from edit 22).
- **No new Python or npm dependencies.** No OCR, no PDF text extraction, no QR library.
- **PDPA:** the uploaded documents carry a 13-digit citizen ID, full address, phone and email. Bytes are held in session state for the life of the run and never written to disk or logged. See ruling D-D.

---

## 0. Evidence — what is actually in `pictures/PEAK export`, measured

Three files, two documents. **`ใบเสร็จ (1).pdf` and `ใบเสร็จ (2).pdf` are byte-identical** (md5 `4cc5a9da6bf685572791dd01de19ddd1`).

Both PDFs are **a single JPEG each** — `/Subtype /Image`, `/Filter /DCTDecode`, 2382×3483, DeviceRGB. **There is no text layer in either file.**

### `ใบแจ้งหนี้.pdf` — invoice IVT-20260700089

| field | value |
|---|---|
| เลขที่เอกสาร | `IVT-20260700089` |
| วันที่ออก / เครดิต / ครบกำหนด | 11/07/2026 · 7 วัน · 18/07/2026 |
| **รหัสลูกค้า** | **`QO-20250500050`** |
| ลูกค้า / เลขที่ภาษี | Wiwat Sintuboon · `3509900107144` (13-digit personal) |
| lines | `Solar Rooftop (On-grid) 3 Phase_10kWp (P00004)` Installment_**M14/48** ฿8,399.00 VAT 7% · three `Late Fee (No VAT) (P00042)` lines M11 (94 days) ฿2,368.52, M12 (64) ฿1,612.61, M13 (27) ฿680.32 |
| total | ฿13,060.45 (ยกเว้นภาษี 4,661.45 + ฐาน 7,849.53 + VAT 549.47) |
| signed | ผู้ออกเอกสาร นันทพล ทับทาบ 29/08/2025 · **ผู้อนุมัติเอกสาร Aynaz Zohrevand 15/07/2026** |

### `ใบเสร็จ.pdf` — receipt RE-20260700272 — **the document that matters**

| field | value |
|---|---|
| เลขที่เอกสาร / วันที่ออก / อ้างอิง | `RE-20260700272` · 16/07/2026 · `BN-20260700032` |
| ลูกค้า | **`99999000132`** Wiwat Sintuboon · เลขที่ภาษี `3509900107144` |
| **settles four invoices** | `IVT-20260400091` ฿8,399.00 · `IVT-20260500090` ฿8,399.00 · `IVT-20260600090` ฿8,399.00 · `IVT-20260700089` ฿13,060.45 |
| paid | **฿38,257.45 on 16/07/2026**, channel `Beam 0001`, WHT 0.00 |

Arithmetic checks out to the satang: 4 × 8,399 = 33,596 VAT-inclusive (÷1.07 = 31,398.12, VAT 2,197.88) and the three late fees sum to 4,661.45 = the `ยกเว้นภาษี` line. **This receipt is a complete, signed allocation.**

### Why that is the pivotal finding

`backend/app/journey.py:323` records every receipt with `is_allocated: False`, `exception_raised: True`, `pending_decision: "OD-02"` — *"recorded, never allocated to components. A real payment is never lost, and never guessed at."* **A PEAK receipt naming the four invoices it cleared is not a guess.** OD-02 exists because the app had no authority for the allocation; this document is one. That makes ruling **D-B** the highest-value question in this plan.

### Three things verified rather than assumed

1. **The join key already exists in our own pipeline.** `scripts/import_master_sheet.py:364` already reads `PEAK Contact Code` and `Invoice Number`, and `backend/app/journey.py:817` already assigns `inv["peak_number"] = row.get("invoice_number")`. Thinly populated in the held render (10 `IVT-` strings in `backend/var/master_sheet.txt`), but the plumbing exists and needs no invention.
2. **Odoo cannot supply payment state.** `data/odoo/account.move.csv` is 236 rows: 234 `entry`, **1** `out_invoice`, 1 `in_invoice`, and `payment_state` is `not_paid` on all 236. This confirms the standing note that no collection history exists in Odoo. Odoo is not a candidate source.
3. **The fine-grained truth already exists and is simply not shown.** `backend/app/journey.py:29` defines `PAID`, `PARTIALLY_PAID`, `OVERDUE` among nine invoice states and they are populated per invoice (`journey.py:813, 868`). The "five values are too coarse" complaint is a *surfacing* problem, not a data problem.

### And one gap the complaint turns out to be literally right about

**The app does not record when the sheet was captured.** `backend/app/book_source.py:97-104` builds the `source` block with `spreadsheet`, `spreadsheet_id`, `render`, `pii`, `blocks` — and **no date**. Confirmed against `fixtures_sheet.json`. So today it is not merely hard to tell how stale a payment status is; it is impossible. §1.3 fixes that.

### OCR is rejected, with the measurement

Parsing these files mechanically would mean OCR of Thai script from a 2382×3483 scan with no text layer, and there is no OCR dependency anywhere in the tree. That is a large new dependency, a new failure mode on every upload, and a wrong number that *looks* right — the exact failure class this codebase calls "a confident wrong number, not a graceful failure" (`Payments.jsx:46`). **Phase C keys the ~6 fields a human can read in 30 seconds and attaches the document as the proof.** The upgrade path, if a spreadsheet report export exists, is ruling **D-A**.

---

## 1. Design

### 1.1 The object

A new module `backend/app/payment_position.py` exposes one pure function. It reads the invoice and receipt stores that already exist and computes nothing the client could see twice.

```python
build(customer, jstate, business_date) -> dict
```

returning:

```python
{
  "paid_count": 11,               # invoices in a settled state
  "open_count": 4,                # invoices in OPEN_INVOICE_STATES
  "total_count": 15,
  "oldest_unpaid": {              # None when nothing is open
      "uid": "inv-00199",
      "peak_number": "IVT-20260400091",   # None when the sheet carried no number
      "due_date": "2026-04-12",
      "outstanding": "8399.00",
  },
  "last_money_in": {              # None when nothing has ever been received
      "amount": "38257.45",
      "on": "2026-07-16",
      "source": "PEAK_DOC",
      "ref": "RE-20260700272",
  },
  "source": "PEAK_DOC",           # SHEET | SLIP | PEAK_DOC — who last moved this
  "as_of": "2026-07-16",          # None when unknowable; see 1.3
  "as_of_days": 57,               # None when as_of is None
  "stale": True,                  # None when as_of is None
  "note_th": "…",
}
```

### 1.2 The provenance rule

`source` and `as_of` name **the newest dated fact that moved the position**:

- a receipt exists → `source` is that receipt's own source, `as_of` is its `received_on`;
- otherwise → `source` is `"SHEET"` and `as_of` is the sheet's capture date.

`SLIP` is a receipt an officer confirmed from a bank slip (the existing `POST /v1/slips` path). `PEAK_DOC` is one applied from an uploaded PEAK document (Phase C). Until Phase C lands, `PEAK_DOC` is never produced — and that is correct, not a stub.

### 1.3 Staleness, and the refusal when it cannot be known

`as_of_days = business_date − as_of`; `stale` is `as_of_days > settings.payment_position_stale_days`, a new setting **defaulting to 30**. Thirty is a chosen default, not a ruled one — overrule it and only the constant changes.

**When `as_of` is unknown the block refuses rather than guesses.** `as_of`, `as_of_days` and `stale` are all `None`, and `note_th` says so in Thai. This is the standing house posture (`StatusPair` refuses a half-pair visibly; `MoneyPosition` returns null rather than invent), applied here.

So §0's gap must be closed for the sheet case to be anything but a permanent refusal: `book_source.py` gains a `captured_on` on the `source` block, carried from the import run's own timestamp. An older fixture without one yields `None` and the honest refusal — never a fabricated date.

### 1.4 Where it is served

`payment_position` rides beside `money_position`, added at the three sites that already build it, and nowhere else:

- `backend/app/routers/journey.py:237` — the work-item row
- `backend/app/routers/today.py:850` — the per-customer invoices endpoint
- `backend/app/routers/today.py:379` — the work-book row projection and its `meta.columns`

### 1.5 The surface

One new component, `frontend/src/components/PaymentPosition.jsx`, in three variants of one definition (the shape `MoneyPosition` already uses — `compact` for rows, full for the case page). It answers the four questions in reading order: **did they pay** (paid/open counts), **how much is left** (oldest unpaid), **when money last came in** (`last_money_in`), **who says so and how fresh** (`source` + `as_of`, with the stale mark).

It sits **beside** `StatusPair`, never replacing it. The chip stays the governed five-value field; the block is the position.

### 1.6 Acting on it

`GET /v1/workbook` gains two filter values on the existing filter machinery (`WorkBook.jsx:284`, `routers/today.py:236`): `position=unpaid` and `position=stale`. Sorting by `oldest_unpaid.due_date` joins the existing `SORTABLE` set (`WorkBook.jsx:156`). No new screen; the book becomes the worklist.

### 1.7 The upload (Phase C)

`POST /v1/peak-documents:inbound` — **raw body, exactly the shape `routers/imports.py` had to use** (no `python-multipart`, no `UploadFile`; that parameter raises at route-decoration time and would stop the app booting). Magic-byte sniff for `%PDF-`; 5 MB cap enforced both by `Content-Length` pre-check and a running counter over `request.stream()`.

The run holds the bytes in session state, plus `sha256`, `size`, `filename`, `uploaded_by`, `uploaded_at`. The officer then keys the document: kind (`INVOICE` or `RECEIPT`), number, date, total, and for a receipt the invoice numbers it settles. The run answers with a **proposal per named invoice** — matched against `inv["peak_number"]` — and applies nothing.

`POST /v1/peak-documents/{uid}:apply` with `by` and a reason applies it. Only then do invoice states move and a receipt row appear with `source: "PEAK_DOC"`.

**An unmatched invoice number is reported, never invented.** A receipt naming an invoice we do not hold yields a row marked `UNMATCHED` with the number printed; the rest of the receipt still applies. Partial application is explicit and counted in the run report, which is the three-state reconciliation `imports.py` already established.

---

## 2. Decisions required before Phase C

Phases A and B are unblocked and build on evidence already in hand. **Phase C needs five rulings.** They are listed here as questions, not tasks, and nothing in Phase C starts until they are answered.

| # | decision | why it cannot be guessed |
|---|---|---|
| **D-A** | **Does PEAK export a spreadsheet report** (xlsx/csv) of invoices or receipts? | If yes, Phase C parses a file with the existing `imports.py` sniffer and the keying in §1.7 mostly disappears. This is the largest single lever in the plan and only Arina can answer it. Phase C as written assumes **no**. |
| **D-B** | **OD-02: may a PEAK receipt's own allocation be recorded as an allocation?** | `journey.py:323` hard-codes `is_allocated: False` because the app had no authority. RE-20260700272 names its four invoices and is signed. Ruling yes sets `is_allocated: True` **for PEAK_DOC receipts only**, leaving slip receipts untouched. Ruling no means Phase C moves invoice states but leaves the receipt unallocated, which still works and is still useful. |
| **D-C** | **Which identifier is the customer join key?** | Three appear on these two documents and they disagree in shape: `รหัสลูกค้า QO-20250500050` (invoice), `99999000132` (receipt, before the name), `เลขที่ภาษี 3509900107144` (both). The sheet already has a `PEAK Contact Code` column (`import_master_sheet.py:364`). Which one is authoritative? |
| **D-D** | **Where do uploaded PDFs live, and for how long?** | They carry a citizen ID, full address, phone and email. The plan holds bytes in session state only and never writes them to disk — but that means the document is gone when the session ends, and the case keeps only the keyed fields plus the sha256. Durable storage is a PDPA decision and a GCP decision, not a UI one. |
| **D-E** | **May `payment_status` stay at five values?** | The plan assumes **yes** (REQ-COL-075 governs it) and puts all new detail in `payment_position`. Confirm, because the alternative is a spec change upstream of this code. |

**One observation for D-C, offered as evidence not a conclusion:** `backend/app/fixtures.py:127` states that *"no citizen or juristic id exists anywhere upstream."* Both of these PEAK documents print one. `A4-drive-folder-evidence.md` already recorded that the comment's true scope is "not in Odoo, not in the sheet" — these files are the second confirmation.

---

## Phase A — the object and its provenance

### Task 0: Measure the baseline, because the recorded one lags the branch

This task writes no code. The test contract is "green at or above the measured
baseline, counts pasted" — and the recorded figure has been wrong against this
branch before. Measure it on the tree you are about to change.

**Files:** none.

- [x] **Step 1: Confirm the working tree is the one being measured**

Run: `git status --short`
Expected: whatever is uncommitted is listed. Do not stash it — the branch's own
working tree is the baseline, not `HEAD`.

- [x] **Step 2: Run the backend suite**

Run: `cd backend && python -m pytest`
Expected: a pass/skip count. **Run it WITHOUT `-q`** — `pytest.ini` already sets it
and doubling it hides the summary line. Record the number.

- [x] **Step 3: Run the frontend suite**

Run: `cd frontend && npx vitest run`
Expected: a passed count and a file count. Record both.

- [x] **Step 4: Run the whole harness**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED, with the e2e count. Note that `verify_all.sh` prints
counts but **does not enforce them** — the budget is a human convention, so the
number only exists if you write it down.

**MEASURED 2026-09-11 on `design-team` with its 49 uncommitted files:**

| suite | baseline |
|---|---|
| backend | **618 passed, 1 skipped** (83.11s) |
| frontend | **511 passed, 40 files** (8.94s) |
| e2e | **29 checks, 29 passed** |
| `./scripts/verify_all.sh` | **EVERYTHING PASSED** |

The recorded figure was 610/496/29. **Backend had moved +8 and frontend +15 (and +2 files) against the branch** — the reason this task exists.

- [x] **Step 5: Write the three numbers into this plan under Task 0 and commit**

```bash
git add docs/archive/superpowers/plans/2026-09-11-peak-upload-payment-position.md
git commit -m "docs(plan): record the measured baseline before Phase A"
```

---

### Task 1: The capture date the sheet never recorded

**Files:**
- Modify: `backend/app/book_source.py:97-104`
- Test: `backend/tests/test_payment_position.py` (create)

**Interfaces:**
- Produces: `book_source.build()["source"]["captured_on"]` — an ISO date string, or `None` when the run carries no timestamp.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_payment_position.py
"""Payment position — the block, its provenance, and its refusal (plan 2026-09-11)."""
from app import book_source


def test_the_source_block_carries_a_capture_date_or_says_it_cannot():
    source = book_source.build()["source"]
    assert "captured_on" in source, "the source block must say when the sheet was captured"
    # An older fixture legitimately has none. What is forbidden is the key being absent,
    # because then no caller can tell "unknown" from "never asked".
    assert source["captured_on"] is None or isinstance(source["captured_on"], str)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: FAIL — `KeyError` / assertion on `"captured_on" in source`.

- [ ] **Step 3: Add the field**

In `backend/app/book_source.py`, inside the `"source"` dict (after `"render"`):

```python
            # Plan 2026-09-11 §1.3: without this, no caller can tell how stale a
            # payment status is — the gap the payment position exists to close.
            # None when the run carries no timestamp: unknown, never invented.
            "captured_on": (run.get("captured_on") or meta.get("captured_on") or None),
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/book_source.py backend/tests/test_payment_position.py
git commit -m "feat(book): the source block says when the sheet was captured, or that it cannot"
```

---

### Task 2: `payment_position.build`

**Files:**
- Create: `backend/app/payment_position.py`
- Modify: `backend/app/config.py` (add `payment_position_stale_days: int = 30` beside `late_payment_grace_days:175`)
- Test: `backend/tests/test_payment_position.py`

**Interfaces:**
- Consumes: `book_source.build()["source"]["captured_on"]` (Task 1).
- Produces: `payment_position.build(customer, jstate, business_date) -> dict` with exactly the keys in §1.1. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_payment_position.py`:

```python
import datetime
import pytest

from app import journey, payment_position
from app.config import settings


@pytest.fixture
def jstate():
    journey.reset()
    yield journey.for_current()
    journey.reset()


def _customer_with(jstate, invoices, receipts=()):
    """A customer whose contracts own exactly these invoices."""
    customer = next(iter(journey.for_current().customers.values()))
    contract_uid = customer.contracts[0].uid
    jstate.invoices.clear()
    jstate.receipts.clear()
    for amount, due, state, peak_number in invoices:
        inv = journey.make_invoice(jstate, contract_uid, "SPV", "INSTALMENT",
                                   amount, due, state)
        inv["peak_number"] = peak_number
    for amount, on, source, ref in receipts:
        rcp = journey.make_receipt(jstate, contract_uid, "SPV", amount, on)
        rcp["source"], rcp["ref"] = source, ref
    return customer


def test_it_counts_paid_and_open_and_names_the_oldest_unpaid(jstate):
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 4, 12), "PAID", "IVT-20260400091"),
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", "IVT-20260500090"),
        ("8399.00", datetime.date(2026, 6, 18), "OVERDUE", "IVT-20260600090"),
    ])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["paid_count"] == 1
    assert block["open_count"] == 2
    assert block["total_count"] == 3
    assert block["oldest_unpaid"]["peak_number"] == "IVT-20260500090"
    assert block["oldest_unpaid"]["due_date"] == "2026-05-12"


def test_with_no_receipt_the_source_is_the_sheet(jstate):
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", None)])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "SHEET"
    assert block["last_money_in"] is None


def test_a_receipt_moves_the_source_and_the_as_of_to_the_receipt(jstate):
    customer = _customer_with(
        jstate,
        [("8399.00", datetime.date(2026, 5, 12), "PAID", "IVT-20260500090")],
        [("38257.45", "2026-07-16", "PEAK_DOC", "RE-20260700272")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "PEAK_DOC"
    assert block["as_of"] == "2026-07-16"
    assert block["last_money_in"] == {
        "amount": "38257.45", "on": "2026-07-16",
        "source": "PEAK_DOC", "ref": "RE-20260700272"}


def test_the_newest_receipt_wins_not_the_last_one_stored(jstate):
    customer = _customer_with(
        jstate,
        [("8399.00", datetime.date(2026, 5, 12), "PAID", None)],
        [("38257.45", "2026-07-16", "PEAK_DOC", "RE-20260700272"),
         ("8399.00", "2026-03-02", "SLIP", "slip-0001")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["as_of"] == "2026-07-16", "the newest dated fact, not insertion order"
    assert block["source"] == "PEAK_DOC"


def test_staleness_is_measured_from_the_as_of(jstate):
    customer = _customer_with(
        jstate,
        [("8399.00", datetime.date(2026, 5, 12), "PAID", None)],
        [("8399.00", "2026-09-01", "SLIP", "slip-0001")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["as_of_days"] == 10
    assert block["stale"] is False
    block = payment_position.build(customer, jstate, datetime.date(2026, 12, 1))
    assert block["stale"] is True


def test_an_unknowable_as_of_refuses_rather_than_guesses(jstate, monkeypatch):
    monkeypatch.setattr(payment_position, "_sheet_captured_on", lambda: None)
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", None)])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["as_of"] is None
    assert block["as_of_days"] is None
    assert block["stale"] is None, "unknown is not fresh — it is unknown"
    assert "ไม่ทราบ" in block["note_th"]


def test_every_figure_is_a_string_so_the_client_never_does_arithmetic(jstate):
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", "IVT-20260500090")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert isinstance(block["oldest_unpaid"]["outstanding"], str)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.payment_position'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/payment_position.py
"""The payment position — plan 2026-09-11 §1.1.

Four questions in one server-owned block: did they pay, how much is left, when did
money last come in, and WHO SAYS SO. The fourth is the one nothing in this codebase
could answer before: `payment_status` is a five-value field derived from the sheet
(`cases.py:517`) and it carried no source and no date.

Every figure is produced here, once, as a string. `api.js:1-4` forbids the client
recomputing a number the server owns, and nothing in this block invites it to.

The refusal is deliberate. When the sheet's capture date is unknown, `as_of`,
`as_of_days` and `stale` are all None — not "fresh", not today's date. The same
posture StatusPair takes on a half-pair and MoneyPosition takes on a missing block:
a mark that says nothing is worse than one that says it knows nothing.
"""
from decimal import Decimal

from . import book_source
from .config import settings

# journey.py:29's nine states, split into the two questions this block asks.
OPEN_STATES = ("ISSUED", "SENT", "PARTIALLY_PAID", "OVERDUE")
SETTLED_STATES = ("PAID",)

SOURCES = ("SHEET", "SLIP", "PEAK_DOC")

NOTE_UNKNOWN_TH = ("ไม่ทราบว่าข้อมูลการชำระนี้เป็นข้อมูล ณ วันใด — ชีตที่นำเข้าไม่ได้บันทึกวันที่ดึงข้อมูล "
                   "จึงบอกไม่ได้ว่าเก่าแค่ไหน")
NOTE_SHEET_TH = "ข้อมูลการชำระมาจากชีต ณ วันที่ %s"
NOTE_RECEIPT_TH = {
    "SLIP": "ข้อมูลล่าสุดมาจากสลิปที่เจ้าหน้าที่ยืนยัน เมื่อ %s",
    "PEAK_DOC": "ข้อมูลล่าสุดมาจากเอกสาร PEAK ที่อัปโหลด เมื่อ %s",
}
NOTE_STALE_TH = " · เก่ากว่า %d วัน ควรตรวจสอบกับ PEAK"


def _sheet_captured_on():
    """Task 1's field. A seam, so a test can make it unknown without a fixture."""
    return (book_source.build().get("source") or {}).get("captured_on")


def _money(raw):
    return str(Decimal(str(raw)).quantize(Decimal("0.01")))


def _customer_invoices(customer, jstate):
    contract_uids = {k.uid for k in customer.contracts}
    return [inv for inv in jstate.invoices.values() if inv["contract_uid"] in contract_uids]


def _customer_receipts(customer, jstate):
    contract_uids = {k.uid for k in customer.contracts}
    return [r for r in jstate.receipts.values() if r["contract_uid"] in contract_uids]


def _oldest_unpaid(invoices):
    open_rows = [i for i in invoices if i["state"] in OPEN_STATES]
    if not open_rows:
        return None
    # due_date may be None on a row the sheet never dated; those sort last rather
    # than first, so a dateless row never impersonates the oldest debt.
    oldest = min(open_rows, key=lambda i: (i["due_date"] is None, i["due_date"] or "", i["uid"]))
    outstanding = oldest.get("outstanding")
    if outstanding in (None, ""):
        outstanding = oldest["amount"]
    return {
        "uid": oldest["uid"],
        "peak_number": oldest.get("peak_number"),
        "due_date": oldest["due_date"],
        "outstanding": _money(outstanding),
    }


def _last_money_in(receipts):
    if not receipts:
        return None
    newest = max(receipts, key=lambda r: (r.get("received_on") or "", r["uid"]))
    source = newest.get("source") or "SLIP"
    return {
        "amount": _money(newest["amount"]),
        "on": newest.get("received_on"),
        "source": source if source in SOURCES else "SLIP",
        "ref": newest.get("ref") or newest["uid"],
    }


def build(customer, jstate, business_date):
    invoices = _customer_invoices(customer, jstate)
    receipts = _customer_receipts(customer, jstate)
    last_in = _last_money_in(receipts)

    if last_in is not None and last_in["on"]:
        source, as_of = last_in["source"], last_in["on"]
        note = NOTE_RECEIPT_TH.get(source, NOTE_RECEIPT_TH["SLIP"]) % as_of
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
        "source": source,
        "as_of": as_of,
        "as_of_days": as_of_days,
        "stale": stale,
        "note_th": note,
    }


def _date(raw):
    from datetime import date
    y, m, d = (int(p) for p in str(raw).split("-"))
    return date(y, m, d)
```

Then in `backend/app/config.py`, beside `late_payment_grace_days` (line 175):

```python
    # Plan 2026-09-11 §1.3. A chosen default, not a ruled one.
    payment_position_stale_days: int = 30
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 5: Run the whole backend suite to prove nothing else moved**

Run: `cd backend && python -m pytest`
Expected: the Task 0 baseline plus 8. **Paste the count.** Any pre-existing test that now fails is escalated, not edited.

- [ ] **Step 6: Commit**

```bash
git add backend/app/payment_position.py backend/app/config.py backend/tests/test_payment_position.py
git commit -m "feat(payments): the payment position, with its source and how fresh it is"
```

---

### Task 3: Serve it on the three rows that already carry money_position

**Files:**
- Modify: `backend/app/routers/journey.py:237`
- Modify: `backend/app/routers/today.py:850-863`
- Modify: `backend/app/routers/today.py:379` and its `meta.columns`
- Test: `backend/tests/test_payment_position.py`

**Interfaces:**
- Consumes: `payment_position.build` (Task 2).
- Produces: `payment_position` on the work-item row, the per-customer invoices payload, and the work-book row. Consumed by Tasks 4–7.

- [ ] **Step 1: Write the failing test**

```python
def test_the_three_surfaces_that_serve_money_position_also_serve_the_position(client):
    """One rule, three surfaces: wherever the officer is told the money, she is
    told who says so. A surface that has one and not the other is the scatter
    this block exists to end."""
    item = client.get("/v1/today").json()["items"][0]
    assert "payment_position" in item
    assert item["payment_position"]["source"] in ("SHEET", "SLIP", "PEAK_DOC")

    invoices = client.get(
        "/v1/cases/by-customer/%s/invoices" % item["customer"]["uid"]).json()
    assert "payment_position" in invoices

    book = client.get("/v1/workbook").json()
    assert "payment_position" in book["rows"][0]
    assert "payment_position" in book["meta"]["columns"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -k three_surfaces -v`
Expected: FAIL — `KeyError: 'payment_position'`.

- [ ] **Step 3: Add it at the three sites**

`routers/journey.py`, beside line 237:

```python
        "money_position": money_position(customer, total),
        # Plan 2026-09-11 §1.4: the position rides beside the money, never apart
        # from it — the two answer one question between them.
        "payment_position": payment_position.build(customer, journey.for_current(), settings.business_date),
```

`routers/today.py:861`, in the invoices payload:

```python
    return {"invoices": rows, "customer_uid": customer_uid, "money_position": position,
            "payment_position": payment_position.build(customer, jstate, settings.business_date),
```

`routers/today.py:379`, in the work-book row projection, and add `"payment_position"` to the `meta.columns` list at the same site.

Add `from .. import payment_position` to both routers.

- [ ] **Step 4: Run it and watch it pass**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && python -m pytest`
Expected: baseline + 9. **Paste the count.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/journey.py backend/app/routers/today.py backend/tests/test_payment_position.py
git commit -m "feat(api): serve the payment position wherever money_position is served"
```

---

## Phase B — the surface

### Task 4: Measure the density budget before touching CustomerCase

This task writes no product code. It exists because edit 22 came in over price by missing exactly this file, and the lesson was recorded: **price any CustomerCase addition against `density.test.jsx` before quoting, not after.**

**Files:**
- Read only: `frontend/src/density.test.jsx`

- [ ] **Step 1: Run the density test alone and record the current numbers**

Run: `cd frontend && npx vitest run src/density.test.jsx`
Expected: PASS. **Record the actual pre-contact and worked element counts it prints or asserts against** (the caps are 76 / 112).

- [ ] **Step 2: Write the headroom into the plan file**

Append the two measured numbers and the headroom to this document under Task 4. If headroom is under 4 elements, **stop and escalate to Arina before Task 6** — the case-page variant then costs a test edit, which is not authorised by this plan.

- [ ] **Step 3: Commit the measurement**

```bash
git add docs/archive/superpowers/plans/2026-09-11-peak-upload-payment-position.md
git commit -m "docs(plan): record the density headroom before the case-page change"
```

---

### Task 5: The `PaymentPosition` component

**Files:**
- Create: `frontend/src/components/PaymentPosition.jsx`
- Create: `frontend/src/components/PaymentPosition.test.jsx`
- Modify: `frontend/src/i18n-ops.js` (the table where EN/TH parity is actually enforced by `i18n.test.js`)

**Interfaces:**
- Consumes: the `payment_position` block from Task 3.
- Produces: `<PaymentPosition pp={…} compact={false} />`. Consumed by Tasks 6 and 7.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/PaymentPosition.test.jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { PaymentPosition } from './PaymentPosition.jsx'
import { withPrefs } from '../test-utils.jsx'

const FULL = {
  paid_count: 11, open_count: 4, total_count: 15,
  oldest_unpaid: { uid: 'inv-00199', peak_number: 'IVT-20260400091',
                   due_date: '2026-04-12', outstanding: '8399.00' },
  last_money_in: { amount: '38257.45', on: '2026-07-16',
                   source: 'PEAK_DOC', ref: 'RE-20260700272' },
  source: 'PEAK_DOC', as_of: '2026-07-16', as_of_days: 57, stale: true,
  note_th: 'ข้อมูลล่าสุดมาจากเอกสาร PEAK ที่อัปโหลด เมื่อ 2026-07-16',
}

describe('PaymentPosition', () => {
  it('names the source, so the officer knows who says this', () => {
    render(withPrefs(<PaymentPosition pp={FULL} />))
    expect(screen.getByTestId('pp-source')).toHaveAttribute('data-source', 'PEAK_DOC')
  })

  it('marks a stale position rather than showing it as current', () => {
    render(withPrefs(<PaymentPosition pp={FULL} />))
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
  })

  it('does not mark a fresh position', () => {
    render(withPrefs(<PaymentPosition pp={{ ...FULL, stale: false, as_of_days: 3 }} />))
    expect(screen.queryByTestId('pp-stale')).toBeNull()
  })

  it('an unknown as_of is drawn as unknown, never as fresh', () => {
    render(withPrefs(<PaymentPosition
      pp={{ ...FULL, as_of: null, as_of_days: null, stale: null }} />))
    expect(screen.getByTestId('pp-asof-unknown')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-stale')).toBeNull()
  })

  it('prints the served figure and computes nothing', () => {
    render(withPrefs(<PaymentPosition pp={FULL} />))
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('8,399.00')
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('IVT-20260400091')
  })

  it('renders nothing at all when the API does not carry the block', () => {
    const { container } = render(withPrefs(<PaymentPosition pp={null} />))
    expect(container).toBeEmptyDOMElement()
  })

  it('the compact variant drops the note but keeps the source and the stale mark', () => {
    render(withPrefs(<PaymentPosition pp={FULL} compact />))
    expect(screen.getByTestId('pp-source')).toBeInTheDocument()
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-note')).toBeNull()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/components/PaymentPosition.test.jsx`
Expected: FAIL — cannot resolve `./PaymentPosition.jsx`.

- [ ] **Step 3: Write the component**

```jsx
// frontend/src/components/PaymentPosition.jsx
import { useT } from '../prefs.jsx'
import { format } from './Money.jsx'

// Plan 2026-09-11 §1.5. Four questions in reading order: did they pay, how much is
// left, when money last came in, and who says so. The fourth is the new one — the
// five-value payment_status chip beside this block carries no source and no date,
// and until now neither did anything else on the page.
//
// This sits BESIDE StatusPair and never replaces it. REQ-COL-075 governs that field;
// this block is the position, not the status.
//
// Nothing here computes. Every figure arrives quantised from payment_position.build
// (api.js:1-4), and `format` only puts separators on a string the server decided.
export function PaymentPosition({ pp, compact = false }) {
  const t = useT()
  if (!pp || typeof pp !== 'object') return null
  const oldest = pp.oldest_unpaid
  const lastIn = pp.last_money_in
  return (
    <div className={`pp${compact ? ' pp--compact' : ''}`} data-testid="payment-position">
      <p className="pp__counts">
        {t('pp.counts', { paid: pp.paid_count, open: pp.open_count, total: pp.total_count })}
      </p>
      {oldest && (
        <p className="pp__oldest" data-testid="pp-oldest">
          {t('pp.oldest', {
            amount: format(oldest.outstanding),
            ref: oldest.peak_number || oldest.uid,
            due: oldest.due_date || '—',
          })}
        </p>
      )}
      {lastIn && (
        <p className="pp__lastin" data-testid="pp-lastin">
          {t('pp.lastIn', { amount: format(lastIn.amount), on: lastIn.on, ref: lastIn.ref })}
        </p>
      )}
      <p className="pp__prov">
        <span className="pp__source" data-testid="pp-source" data-source={pp.source}>
          {t(`pp.source.${pp.source}`)}
        </span>
        {/* Unknown is drawn as unknown. A missing capture date must never read as
            "current" — that is the exact dishonesty this block was added to end. */}
        {pp.as_of
          ? <span className="pp__asof">{t('pp.asOf', { on: pp.as_of, days: pp.as_of_days })}</span>
          : <span className="pp__asof pp__asof--unknown" data-testid="pp-asof-unknown">{t('pp.asOfUnknown')}</span>}
        {pp.stale === true && (
          <span className="pp__stale" data-testid="pp-stale">{t('pp.stale')}</span>
        )}
      </p>
      {!compact && pp.note_th && <p className="pp__note" data-testid="pp-note">{pp.note_th}</p>}
    </div>
  )
}
```

Add to `frontend/src/i18n-ops.js`, both EN and TH (parity is enforced by `i18n.test.js`; interpolation slots must match exactly):

```js
  'pp.counts':          { en: 'Paid {paid} of {total} · {open} open', th: 'ชำระแล้ว {paid} จาก {total} · ค้าง {open}' },
  'pp.oldest':          { en: 'Oldest unpaid {ref} · {amount} · due {due}', th: 'ค้างนานสุด {ref} · {amount} · ครบกำหนด {due}' },
  'pp.lastIn':          { en: 'Last money in {amount} on {on} ({ref})', th: 'เงินเข้าล่าสุด {amount} เมื่อ {on} ({ref})' },
  'pp.source.SHEET':    { en: 'from the sheet', th: 'จากชีต' },
  'pp.source.SLIP':     { en: 'from a confirmed slip', th: 'จากสลิปที่ยืนยันแล้ว' },
  'pp.source.PEAK_DOC': { en: 'from a PEAK document', th: 'จากเอกสาร PEAK' },
  'pp.asOf':            { en: 'as of {on} ({days}d)', th: 'ณ {on} ({days} วัน)' },
  'pp.asOfUnknown':     { en: 'date unknown', th: 'ไม่ทราบวันที่' },
  'pp.stale':           { en: 'stale', th: 'ข้อมูลเก่า' },
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd frontend && npx vitest run src/components/PaymentPosition.test.jsx src/i18n.test.js`
Expected: PASS — 7 new, and `i18n.test.js` still green on parity.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PaymentPosition.jsx frontend/src/components/PaymentPosition.test.jsx frontend/src/i18n-ops.js
git commit -m "feat(ui): one block for the payment position, with who says so and how fresh"
```

---

### Task 6: Mount it on the three screens

**Files:**
- Modify: `frontend/src/screens/CustomerCase.jsx:597` (beside `MoneyPosition`)
- Modify: `frontend/src/screens/Today.jsx:1281` (compact, in the row)
- Modify: `frontend/src/screens/WorkBook.jsx:448` (compact, in the money column)
- Test: `frontend/src/screens/Payments.test.jsx` is untouched; assertions go in the existing screen test files as **additions**

**Interfaces:**
- Consumes: `<PaymentPosition />` (Task 5) and the served block (Task 3).

- [ ] **Step 1: Write the failing tests** — one per screen, appended to that screen's existing test file

```jsx
// append to frontend/src/screens/CustomerCase.test.jsx
it('the case page says who last moved the payment position', async () => {
  renderCase()
  expect(await screen.findByTestId('payment-position')).toBeInTheDocument()
  expect(screen.getByTestId('pp-source')).toBeInTheDocument()
})
```

```jsx
// append to frontend/src/screens/Today.test.jsx
it('a queue row carries the compact payment position', async () => {
  renderToday()
  const rows = await screen.findAllByTestId('payment-position')
  expect(rows.length).toBeGreaterThan(0)
})
```

```jsx
// append to frontend/src/screens/WorkBook.test.jsx
it('the book row carries the compact payment position', async () => {
  renderBook()
  expect(await screen.findAllByTestId('payment-position')).not.toHaveLength(0)
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd frontend && npx vitest run src/screens/CustomerCase.test.jsx src/screens/Today.test.jsx src/screens/WorkBook.test.jsx`
Expected: FAIL — `payment-position` not found, three times.

- [ ] **Step 3: Mount it**

`CustomerCase.jsx`, immediately after the `MoneyPosition` at line 597:

```jsx
          <PaymentPosition pp={item?.payment_position} />
```

`Today.jsx`, after the `MoneyPosition` at line 1281:

```jsx
          <PaymentPosition pp={item.payment_position} compact />
```

`WorkBook.jsx`, in the money column render at line 448:

```jsx
      render: (r) => (<>
        <Money arrears={r.aggregate_overdue} balance={r.aggregate_outstanding} />
        <PaymentPosition pp={r.payment_position} compact />
      </>) },
```

Add the import to each of the three files.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd frontend && npx vitest run src/screens/CustomerCase.test.jsx src/screens/Today.test.jsx src/screens/WorkBook.test.jsx`
Expected: PASS.

- [ ] **Step 5: Run the density ratchet — the file that breaks silently**

Run: `cd frontend && npx vitest run src/density.test.jsx`
Expected: PASS. **If it fails, do not raise the cap.** Make the case-page variant render fewer elements (drop the counts line on the case page, where `MoneyPosition` already states the money) and re-run. Raising a ratchet is a test edit and is not authorised by this plan.

- [ ] **Step 6: Run the whole frontend suite and the build**

Run: `cd frontend && npx vitest run && npx vite build`
Expected: PASS, baseline + 10. **Paste the count.**

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/CustomerCase.jsx frontend/src/screens/Today.jsx frontend/src/screens/WorkBook.jsx frontend/src/screens/CustomerCase.test.jsx frontend/src/screens/Today.test.jsx frontend/src/screens/WorkBook.test.jsx
git commit -m "feat(screens): the payment position on the case, the queue and the book"
```

---

### Task 7: Make the book act on it

**Files:**
- Modify: `backend/app/routers/today.py:236` (the `workbook` query parameters)
- Modify: `frontend/src/screens/WorkBook.jsx:27` (`EMPTY_FILTERS`), `:156` (`SORTABLE`), `:284` (the filter bar)
- Test: `backend/tests/test_payment_position.py`, `frontend/src/screens/WorkBook.test.jsx`

**Interfaces:**
- Consumes: the served `payment_position` (Task 3).
- Produces: `GET /v1/workbook?position=unpaid|stale`, and `oldest_unpaid` as a sort key.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_payment_position.py
def test_the_book_filters_to_the_unpaid_and_to_the_stale(client):
    everyone = client.get("/v1/workbook").json()["rows"]
    unpaid = client.get("/v1/workbook?position=unpaid").json()["rows"]
    assert len(unpaid) <= len(everyone)
    assert all(r["payment_position"]["open_count"] > 0 for r in unpaid)

    stale = client.get("/v1/workbook?position=stale").json()["rows"]
    assert all(r["payment_position"]["stale"] is True for r in stale)


def test_an_unknown_position_filter_is_refused_not_ignored(client):
    answer = client.get("/v1/workbook?position=banana")
    assert answer.status_code == 422, "a filter that silently matches everything is a lie"
```

```jsx
// append to frontend/src/screens/WorkBook.test.jsx
it('offers the unpaid and the stale as filters', async () => {
  renderBook()
  const filter = await screen.findByLabelText(/position|สถานะการชำระ/i)
  expect(filter).toBeInTheDocument()
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && python -m pytest tests/test_payment_position.py -k "book_filters or unknown_position" -v`
Expected: FAIL — the parameter is ignored, so `unpaid` equals `everyone` and `banana` returns 200.

- [ ] **Step 3: Implement the filter**

In `routers/today.py`, add `position: str = Query(default=None)` to the `workbook` signature, and after the rows are projected:

```python
    if position is not None:
        if position not in ("unpaid", "stale"):
            raise errors.validation_failed([{
                "pointer": "/position", "code": "value_unknown",
                "message": "position is 'unpaid' or 'stale'; %r is neither." % position,
                "message_th": "ตัวกรองสถานะการชำระรับเฉพาะ unpaid หรือ stale"}])
        # A filter that matched everything on a typo would be worse than an error:
        # the officer would work a list she believed was filtered. Hence the 422.
        if position == "unpaid":
            rows = [r for r in rows if (r.get("payment_position") or {}).get("open_count")]
        else:
            rows = [r for r in rows if (r.get("payment_position") or {}).get("stale") is True]
```

In `WorkBook.jsx`: add `position: ''` to `EMPTY_FILTERS`, add `'oldest_unpaid'` to `SORTABLE` with the accessor `(r) => r.payment_position?.oldest_unpaid?.due_date`, and add the filter to the bar at line 284 following the exact shape of the `payment_status` filter beside it.

- [ ] **Step 4: Run them and watch them pass**

Run: `cd backend && python -m pytest tests/test_payment_position.py -v && cd ../frontend && npx vitest run src/screens/WorkBook.test.jsx`
Expected: PASS.

- [ ] **Step 5: Run everything**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED. **Paste backend / frontend / e2e counts.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/today.py backend/tests/test_payment_position.py frontend/src/screens/WorkBook.jsx frontend/src/screens/WorkBook.test.jsx
git commit -m "feat(book): filter and sort the book by the payment position"
```

---

## Phase C — the PEAK document upload

> **GATED.** Do not start Phase C until D-A through D-E in §2 are ruled. The task
> breakdown below is deliberately not written yet, because D-A alone decides whether
> Phase C parses a spreadsheet (reusing `imports.py` wholesale) or keys a document
> (a new form). Writing both would be writing one of them for the bin.

What is settled regardless of the rulings, and can be relied on when Phase C is written:

- The endpoint is `POST /v1/peak-documents:inbound`, raw body, `%PDF-` or spreadsheet magic-byte sniff, 5 MB cap enforced twice — the shape `routers/imports.py:36-79` was forced into and documents the reason for.
- It stages a run and **applies nothing**. `POST /v1/peak-documents/{uid}:apply` is a separate call taking `by` and a reason.
- It never touches `backend/app/integrations/peak.py`. PKD-001 pins that module to four public functions and this path adds none.
- An invoice number the receipt names and we do not hold is reported `UNMATCHED` with the number printed. The rest of the receipt still applies, and the run report counts all three outcomes.
- `payment_position.source` becomes `PEAK_DOC` on apply, which is why Phase A is built first: the surface that shows which source won already exists before a second source exists.

---

## Self-review

**Spec coverage.** §1.1 → Task 2. §1.2 → Task 2 (four provenance tests). §1.3 → Tasks 1 and 2 (the refusal test). §1.4 → Task 3. §1.5 → Tasks 5 and 6. §1.6 → Task 7. §1.7 → Phase C, gated, not tasked.

**All four of Arina's complaints are answered by Phase A+B alone:** no provenance → `source` + `as_of` + the stale mark; too coarse → counts, oldest unpaid and last money in, without touching the governed five-value field; scattered → one component on all three screens; hard to act on → the book filter and sort.

**Placeholders.** None. Phase C is explicitly ungated work awaiting a ruling, listed in §2 as five questions — not a task with "TBD" in it.

**Type consistency.** `payment_position.build(customer, jstate, business_date)` is called with exactly that signature in Task 3's three sites. `pp.oldest_unpaid.peak_number` is produced in Task 2's `_oldest_unpaid` and read in Task 5's component. `pp.source` is one of the three strings in `SOURCES`, produced in Task 2, keyed as `pp.source.{SOURCE}` in Task 5's i18n table, and asserted as `data-source` in both test files.

**Known risk, named.** Task 6 is the one that can come in over price, via `density.test.jsx`. Task 4 exists solely to measure that before Task 6 runs, with an explicit stop-and-escalate if headroom is under 4 elements.
