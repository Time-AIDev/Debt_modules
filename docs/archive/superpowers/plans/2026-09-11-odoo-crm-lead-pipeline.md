# Odoo crm.lead Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Odoo `crm.lead` rows in the landing schema through rules read from a markdown file, by either of two doors the officer chooses — a dropped `.csv`/`.xlsx` of the sheet's `"x"` tab, or a direct Odoo pull.

**Architecture:** Two ingress adapters return the same `list[dict]`, so the transformation never learns which door ran. `rules.py` parses `docs/odoo-comparison/odoo_compare.md` into a `Rules` object; `crm_lead.normalise(rows, rules)` is a pure function returning records plus a per-row verdict; a writer batches them into one `import_run` of source `ODOO` and records an overwrite ledger. `book_source.load()` is untouched — it already reads whatever is in landing.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy Core (`text()` + `executemany`), pytest, React 18 + Vite. No new dependencies — the rules file is parsed as markdown tables, the way `scripts/import_master_sheet.py` already parses the Drive render.

**Spec:** `docs/archive/superpowers/specs/2026-09-11-odoo-crm-lead-pipeline-design.md`

## Global Constraints

- **Rules live in `docs/odoo-comparison/odoo_compare.md`, never in Python.** No constant in code may restate a mapping, translation or rejection rule that file holds.
- **No second parser.** CSV and XLSX come from `imports.decode_csv` / `imports.read_xlsx`, imported. Writing another is ruling 36's second-pattern MAJOR.
- **Precedence is `landing._PRECEDENCE` unchanged:** ODOO ahead of SHEET. Do not edit that clause.
- **Nothing falls back silently.** A missing rules file, an unreachable Odoo, a rejected row, an unmapped vocabulary value: each is refused or recorded, never defaulted past.
- **Every landed row carries `reason = "no money row in Odoo"`.** Odoo holds no debt; no row may be given a contract, a balance or a zero that looks like one.
- **Test contract:** 569 backend / 443 frontend / 29 e2e must all still pass. New tests add to those counts.
- **Officer-facing strings are bilingual** — English `message` plus Thai `message_th`, as every other refusal in `app/errors.py` already is.
- **Manager-only**, matching `routers/integrations.py:_manager_only`: role in `('MANAGER', 'OWNER')`, else `DEBT-IAM-0403`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/pipelines/__init__.py` | Package marker only |
| `backend/app/pipelines/rules.py` | Parse the markdown rules file into `Rules`. No network, no DB |
| `backend/app/pipelines/crm_lead.py` | `normalise(rows, rules)` — pure. Join, map, translate, reject, verdict |
| `backend/app/pipelines/ingress.py` | `from_odoo(rules)` and `from_upload(raw, filename)` → the same shape |
| `backend/app/pipelines/writer.py` | Batched landing writes + the overwrite ledger |
| `backend/app/routers/pipelines.py` | `POST /v1/pipelines/crm-lead:run`, `GET /v1/pipelines/crm-lead/last-run` |
| `frontend/src/components/DropZone.jsx` | Wraps a real `<input type="file">` in a drop target |
| `backend/tests/test_pipeline_rules.py` | Task 1 |
| `backend/tests/test_pipeline_normalise.py` | Tasks 2–4 |
| `backend/tests/test_pipeline_ingress.py` | Task 5 |
| `backend/tests/test_pipeline_writer.py` | Task 6 |
| `backend/tests/test_pipeline_router.py` | Task 7 |
| `frontend/src/components/DropZone.test.jsx` | Task 8 |

---

### Task 1: Parse the rules file

**Files:**
- Create: `backend/app/pipelines/__init__.py` (empty)
- Create: `backend/app/pipelines/rules.py`
- Test: `backend/tests/test_pipeline_rules.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `rules.load(path=None) -> Rules`; `class Rules` with attributes `joins: list[dict]`, `field_map: list[dict]`, `vocab: list[dict]`, `normalisers: list[dict]`, `rejections: list[dict]`, `precedence: list[dict]`; `rules.tables(markdown: str) -> list[tuple[list[str], list[dict]]]`; `class RulesError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
"""The rules file is parsed, not merely read."""
import pytest

from app.pipelines import rules as rules_mod

MINIMAL = """
# Rules

## 1. Join

| Order | Key | Sheet column | crm.lead field | Compare as | Measured |
| --- | --- | --- | --- | --- | --- |
| 1 | phone | Phone | phone | last 9 digits | 58 of 58 |

## 3. Vocabulary

| Field | Odoo value | Sheet value | Seen |
| --- | --- | --- | --- |
| stage_name | Won | Order - Done | measured |
"""


def test_tables_are_read_by_their_header_row():
    found = rules_mod.tables(MINIMAL)
    headers = [h for h, _ in found]
    assert ["Order", "Key", "Sheet column", "crm.lead field",
            "Compare as", "Measured"] in headers


def test_a_table_becomes_dicts_keyed_by_header():
    found = dict((tuple(h), r) for h, r in rules_mod.tables(MINIMAL))
    vocab = found[("Field", "Odoo value", "Sheet value", "Seen")]
    assert vocab == [{"Field": "stage_name", "Odoo value": "Won",
                      "Sheet value": "Order - Done", "Seen": "measured"}]


def test_a_ragged_row_is_refused_by_name():
    bad = MINIMAL.replace("| stage_name | Won | Order - Done | measured |",
                          "| stage_name | Won | Order - Done |")
    with pytest.raises(rules_mod.RulesError) as exc:
        rules_mod.tables(bad)
    assert "Field" in str(exc.value)


def test_the_real_rules_file_loads_and_carries_every_section():
    loaded = rules_mod.load()
    assert len(loaded.joins) == 5
    assert len(loaded.field_map) == 47
    assert len(loaded.vocab) == 5
    assert len(loaded.normalisers) == 7
    assert len(loaded.rejections) == 3
    assert loaded.precedence == [{"Field group": "all", "Winner": "odoo",
                                  "Decided": "2026-09-11"}]


def test_a_missing_rules_file_refuses_rather_than_defaulting(tmp_path):
    with pytest.raises(rules_mod.RulesError) as exc:
        rules_mod.load(tmp_path / "nope.md")
    assert "nope.md" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The rules file, parsed. docs/odoo-comparison/odoo_compare.md is the source of
truth; this module is only the reader.

Markdown tables and not YAML for the same reason import_master_sheet.py reads
markdown tables: the file has to stay readable by the person who edits it, and a
table is the one format that is both. A table is identified by its header row, so
the headers below are a contract with the document.
"""
from pathlib import Path

RULES_PATH = (Path(__file__).resolve().parents[3] / "docs" / "odoo-comparison"
              / "odoo_compare.md")

HEADERS = {
    "joins": ("Order", "Key", "Sheet column", "crm.lead field", "Compare as", "Measured"),
    "field_map": ("Sheet column", "crm.lead field", "Direction", "Note"),
    "vocab": ("Field", "Odoo value", "Sheet value", "Seen"),
    "normalisers": ("Kind", "Input", "Canonical"),
    "rejections": ("Rule", "Condition", "Verdict"),
    "precedence": ("Field group", "Winner", "Decided"),
}


class RulesError(Exception):
    """The rules could not be read. Never caught to fall back on a default — a
    pipeline running on rules nobody can see is the problem this file exists to
    remove."""


class Rules:
    def __init__(self, sections):
        for name in HEADERS:
            setattr(self, name, sections.get(name, []))

    def vocab_for(self, field, odoo_value):
        for row in self.vocab:
            if row["Field"] == field and row["Odoo value"] == odoo_value:
                return row["Sheet value"]
        return None


def _is_divider(cells):
    return set("".join(cells)) <= set("-: ")


def tables(markdown):
    """Every markdown table in the text as (header, rows-as-dicts)."""
    out, header, rows = [], None, []
    for line in markdown.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if _is_divider(cells):
                continue
            if header is None:
                header = cells
            elif len(cells) != len(header):
                raise RulesError(
                    "table %r has a row with %d cells where the header has %d: %r"
                    % (" | ".join(header), len(cells), len(header), " | ".join(cells)))
            else:
                rows.append(dict(zip(header, cells)))
        elif header is not None:
            out.append((header, rows))
            header, rows = None, []
    if header is not None:
        out.append((header, rows))
    return out


def load(path=None):
    path = Path(path) if path else RULES_PATH
    if not path.is_file():
        raise RulesError("the rules file is missing: %s" % path)
    found = {tuple(h): r for h, r in tables(path.read_text(encoding="utf-8"))}
    sections = {}
    for name, header in HEADERS.items():
        if header not in found:
            raise RulesError("%s: no table with header %r" % (path.name, " | ".join(header)))
        sections[name] = found[header]
    return Rules(sections)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_rules.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/__init__.py backend/app/pipelines/rules.py backend/tests/test_pipeline_rules.py
git commit -m "feat(pipelines): the rules file is read by the code, not just by people"
```

---

### Task 2: Normalise a value — dates, phones, money, codes

**Files:**
- Create: `backend/app/pipelines/crm_lead.py`
- Test: `backend/tests/test_pipeline_normalise.py`

**Interfaces:**
- Consumes: `rules.Rules` from Task 1.
- Produces: `crm_lead.as_date(value) -> str|None` (ISO `YYYY-MM-DD`), `crm_lead.as_month(value) -> str|None` (`YYYY-MM`), `crm_lead.phone_key(value) -> str` (last 9 digits, `""` when fewer), `crm_lead.as_money(value) -> Decimal|None`, `crm_lead.translate(field, value, rules) -> tuple[str, bool]` returning `(value, was_mapped)`.

- [ ] **Step 1: Write the failing test**

```python
"""§3 and §4 of the rules file, one test per row of those tables."""
from decimal import Decimal

from app.pipelines import crm_lead, rules as rules_mod

RULES = rules_mod.load()


def test_a_two_digit_year_is_day_first():
    # import_master_sheet.py's own rule: 02/05/24 is 2 May, not 5 February.
    assert crm_lead.as_date("02/05/24") == "2024-05-02"
    assert crm_lead.as_date("2/5/2024") == "2024-05-02"
    assert crm_lead.as_date("2024-05-02T00:00:00") == "2024-05-02"
    assert crm_lead.as_date("") is None
    assert crm_lead.as_date("not a date") is None


def test_month_year_cells_from_both_systems():
    assert crm_lead.as_month("05/24") == "2024-05"
    assert crm_lead.as_month("May 2024") == "2024-05"
    assert crm_lead.as_month("2024-05") == "2024-05"


def test_a_phone_key_is_the_last_nine_digits():
    assert crm_lead.phone_key("+66 92 542 3597") == "925423597"
    assert crm_lead.phone_key("0925423597") == "925423597"
    assert crm_lead.phone_key("123") == ""


def test_money_drops_the_baht_sign_and_the_thousands_comma():
    assert crm_lead.as_money("3,199฿") == Decimal("3199.00")
    assert crm_lead.as_money("") is None


def test_a_listed_code_is_translated_and_says_so():
    assert crm_lead.translate("com_status", "paid_out", RULES) == ("Paid Out", True)
    assert crm_lead.translate("stage_name", "Won", RULES) == ("Order - Done", True)
    assert crm_lead.translate("connection_type", "single_phase", RULES) == ("1", True)


def test_an_unlisted_code_is_title_cased_and_flagged_as_unmapped():
    # 22 of the 23 crm.stage values were never seen. They must surface as
    # "nobody wrote a rule for this", not as a silent guess.
    assert crm_lead.translate("stage_name", "qualified_lead", RULES) == (
        "Qualified Lead", False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -v`
Expected: FAIL — `AttributeError: module 'app.pipelines.crm_lead' has no attribute 'as_date'` (or ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
"""crm.lead rows into book-shaped records. Pure: no clock, no network, no database.

Everything this module decides comes from the Rules object it is handed. When a
rule is missing it says so in the verdict rather than choosing for itself.
"""
import re
from decimal import Decimal, InvalidOperation

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def as_date(value):
    """A date cell as YYYY-MM-DD, or None. Two-digit years are DAY FIRST — the rule
    import_master_sheet.py applies, and the reason 54 of 58 rows once looked like a
    disagreement about a day the two systems agreed on."""
    v = (value or "").strip()
    if not v:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", v)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return "%04d-%02d-%02d" % (y + 2000 if y < 100 else y, mo, d)
    return None


def as_month(value):
    v = (value or "").strip()
    if not v:
        return None
    m = re.match(r"^(\d{4})-(\d{2})$", v)
    if m:
        return "%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})/(\d{2})$", v)
    if m:
        return "%04d-%02d" % (int(m.group(2)) + 2000, int(m.group(1)))
    m = re.match(r"^([A-Za-z]{3})[a-z]* (\d{4})$", v)
    if m and m.group(1).lower() in MONTHS:
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])
    return None


def phone_key(value):
    """Last nine digits: 0925423597 and +66 92 542 3597 are one number."""
    d = re.sub(r"\D", "", value or "")
    return d[-9:] if len(d) >= 9 else ""


def as_money(value):
    m = re.sub(r"[^\d.]", "", value or "")
    try:
        return Decimal(m).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def translate(field, value, rules):
    """(translated, was_mapped). An unmapped snake_case value is title-cased so the
    row still lands, and `was_mapped=False` puts it in the run report — a missing
    rule must be visible, not absorbed."""
    if value in (None, ""):
        return value, True
    mapped = rules.vocab_for(field, value)
    if mapped is not None:
        return mapped, True
    if "_" in str(value):
        return " ".join(w.capitalize() for w in str(value).split("_")), False
    return value, True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/crm_lead.py backend/tests/test_pipeline_normalise.py
git commit -m "feat(pipelines): dates, phones, money and codes normalise before anything compares them"
```

---

### Task 3: Reject a row, by the rule that rejects it

**Files:**
- Modify: `backend/app/pipelines/crm_lead.py`
- Test: `backend/tests/test_pipeline_normalise.py` (append)

**Interfaces:**
- Consumes: Task 2's helpers.
- Produces: `crm_lead.volt_stem(volt_id) -> str`, `crm_lead.rejection_for(row, seen, rules) -> str|None` returning the `Rule` name from §5 or `None` when the row is acceptable.

- [ ] **Step 1: Write the failing test**

```python
def test_a_row_with_neither_a_volt_id_nor_a_phone_is_rejected():
    assert crm_lead.rejection_for({"volt_id": "", "phone": ""}, set(), RULES) == "no_identity"


def test_a_row_with_only_a_phone_is_acceptable():
    assert crm_lead.rejection_for({"volt_id": "", "phone": "0925423597"},
                                  set(), RULES) is None


def test_a_volt_id_of_neither_shape_is_rejected():
    assert crm_lead.rejection_for({"volt_id": "banana", "phone": "0925423597"},
                                  set(), RULES) == "unshaped_volt_id"


def test_both_real_volt_id_shapes_are_accepted():
    # Odoo holds two: the sheet's long form and its own VL/VC form.
    assert crm_lead.rejection_for({"volt_id": "99999000032_Thitipawee_x_IPW"},
                                  set(), RULES) is None
    assert crm_lead.rejection_for({"volt_id": "VL0000143"}, set(), RULES) is None


def test_a_duplicate_volt_id_in_one_run_is_named():
    assert crm_lead.rejection_for({"volt_id": "VL0000143"},
                                  {"VL0000143"}, RULES) == "duplicate_volt_id"


def test_the_stem_is_what_makes_the_two_shapes_one_key():
    assert crm_lead.volt_stem("99999000032_Thitipawee_x_IPW") == "99999000032"
    assert crm_lead.volt_stem("VL0000143") == "VL0000143"
    assert crm_lead.volt_stem("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -k reject -v`
Expected: FAIL — `AttributeError: module 'app.pipelines.crm_lead' has no attribute 'rejection_for'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/pipelines/crm_lead.py`:

```python
VOLT_SHEET_SHAPE = re.compile(r"^\d{6,}_")
VOLT_ODOO_SHAPE = re.compile(r"^V[CL]\d{4,}$", re.I)


def volt_stem(volt_id):
    """The identifying head: 99999000032 out of 99999000032_Thitipawee_.._IPW, and
    VL0000143 out of itself. crm.lead.volt_id holds BOTH shapes, so an exact match
    finds far fewer rows than exist — 0 of 58 against this key's 58 of 58."""
    return (volt_id or "").strip().split("_")[0].strip().upper()


def rejection_for(row, seen, rules):
    """The §5 rule that refuses this row, or None. `seen` is the set of volt_stems
    already taken in this run."""
    volt_id = (row.get("volt_id") or "").strip()
    if not volt_id and not phone_key(row.get("phone") or row.get("mobile") or ""):
        return "no_identity"
    if volt_id and not (VOLT_SHEET_SHAPE.match(volt_id) or VOLT_ODOO_SHAPE.match(volt_id)):
        return "unshaped_volt_id"
    if volt_id and volt_stem(volt_id) in seen:
        return "duplicate_volt_id"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/crm_lead.py backend/tests/test_pipeline_normalise.py
git commit -m "feat(pipelines): a refused row is refused by a named rule"
```

---

### Task 4: normalise() — rows in, records and verdicts out

**Files:**
- Modify: `backend/app/pipelines/crm_lead.py`
- Test: `backend/tests/test_pipeline_normalise.py` (append)

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: `crm_lead.normalise(rows, rules) -> tuple[list[dict], list[dict]]`. Each record is `{"volt_id", "customer_no", "name_roman", "name_th", "epc", "product", "sales_lead", "phone_masked", "phone_e164", "email_masked", "source_refs", "reason", "order"}` — the `landing.CUSTOMER_COLUMNS` shape plus `reason` and a nested `order` dict. Each verdict is `{"volt_id", "verdict", "rule", "unmapped"}` where `verdict` is `"landed"` or `"rejected"`.

- [ ] **Step 1: Write the failing test**

```python
RAW = [
    {"id": "74481", "volt_id": "VL0000143", "contact_name": "ลูกค้าทดสอบ 0005",
     "last_name": "บุญรอด", "phone": "0925423597", "email_from": "a@b.co",
     "stage_name": "Won", "connection_type": "single_phase", "epc": "IPW",
     "submitted_date": "2024-05-02", "contract_signed_date": "2024-05-24",
     "order_type": "leasing", "inverter_kw": "5.0", "monthly_rate": "0.0",
     "user_id": "70|North - Piyabud", "zip": "10150"},
    {"id": "74482", "volt_id": "", "phone": "", "contact_name": "no identity"},
]


def test_every_landed_row_says_odoo_knows_of_no_money():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert [r["reason"] for r in records] == ["no money row in Odoo"]


def test_a_record_carries_the_landing_customer_shape():
    records, _ = crm_lead.normalise(RAW, RULES)
    from app import landing
    for column in landing.CUSTOMER_COLUMNS:
        assert column in records[0]


def test_the_phone_is_kept_for_dialling_and_masked_for_showing():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["phone_e164"] == "0925423597"
    assert "x" in records[0]["phone_masked"]
    assert "5423597" not in records[0]["phone_masked"]


def test_vocabulary_is_applied_to_the_order_block():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["order"]["order_status"] == "Order - Done"


def test_watt_comes_back_in_watts_not_kilowatts():
    # panel_watt is one panel; inverter_kw is the system, and the sheet writes W.
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["order"]["watt"] == 5000


def test_a_rejected_row_is_reported_with_its_rule_and_never_landed():
    records, verdicts = crm_lead.normalise(RAW, RULES)
    assert len(records) == 1
    rejected = [v for v in verdicts if v["verdict"] == "rejected"]
    assert rejected == [{"volt_id": "", "verdict": "rejected",
                         "rule": "no_identity", "unmapped": []}]


def test_an_unmapped_vocabulary_value_travels_on_the_verdict():
    rows = [dict(RAW[0], stage_name="qualified_lead")]
    _, verdicts = crm_lead.normalise(rows, RULES)
    assert verdicts[0]["unmapped"] == [["stage_name", "qualified_lead"]]


def test_normalise_is_pure():
    before = [dict(r) for r in RAW]
    crm_lead.normalise(RAW, RULES)
    assert RAW == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -k normalise -v`
Expected: FAIL — `AttributeError: module 'app.pipelines.crm_lead' has no attribute 'normalise'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/pipelines/crm_lead.py`:

```python
# The §2 rows whose Odoo value needs a shape change on the way in. Everything else
# is copied across as the rules file's field_map says.
DATE_FIELDS = ("submitted_date", "contract_signed_date", "epc_start_date", "epc_end_date")
MONTH_FIELDS = ("epc_start_month_year",)
VOCAB_FIELDS = ("stage_name", "connection_type", "com_status")
WATT_SCALE = 1000            # §2: Odoo writes kW where the sheet writes W


def _label(value):
    """A many2one arrives as "70|North - Piyabud"; the label is what a person reads."""
    text = "" if value is None else str(value)
    return text.split("|", 1)[1].strip() if "|" in text else text


def mask_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 4:
        return "xxx" if digits else None
    return "%sx-xxx-%s" % (digits[:2], digits[-4:])


def mask_email(email):
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    return "%s•••@%s" % (local[:1], domain)


def normalise(rows, rules):
    """(records, verdicts). Pure — `rows` is never mutated.

    A record is the landing.customer shape plus `reason` and a nested `order`. Every
    record carries reason "no money row in Odoo": crm.lead declares monthly_rate,
    dp_amount and energy_bill and fills none of them, so a row that looked like a
    contract here would be a number nobody agreed to bill.
    """
    records, verdicts, seen = [], [], set()
    for row in rows:
        volt_id = (row.get("volt_id") or "").strip()
        rule = rejection_for(row, seen, rules)
        if rule:
            verdicts.append({"volt_id": volt_id, "verdict": "rejected",
                             "rule": rule, "unmapped": []})
            continue
        unmapped = []
        translated = {}
        for field in VOCAB_FIELDS:
            value, was_mapped = translate(field, row.get(field), rules)
            translated[field] = value
            if not was_mapped:
                unmapped.append([field, row.get(field)])

        phone = row.get("phone") or row.get("mobile") or None
        name = _label(row.get("contact_name"))
        watt = as_money(row.get("inverter_kw"))
        order = {
            "crm_id": row.get("id"),
            "order_type": "Leasing" if (row.get("order_type") or "").lower() == "leasing" else "Cash",
            "order_status": translated["stage_name"],
            "loan_status": None,
            "phase": translated["connection_type"],
            "com_status": translated["com_status"],
            "epc": row.get("epc") or None,
            "watt": int(watt * WATT_SCALE) if watt else None,
            "province": row.get("install_province") or None,
            "postal_code": row.get("zip") or None,
            "sales_lead": _label(row.get("user_id")) or None,
            "source_ref": [],
            "data_source": "ODOO",
        }
        for field in DATE_FIELDS:
            order[field] = as_date(row.get(field))
        for field in MONTH_FIELDS:
            order[field] = as_month(row.get(field))
        order["submit_date"] = order.pop("submitted_date")

        records.append({
            "volt_id": volt_id or "phone-%s" % phone_key(phone),
            "customer_no": volt_stem(volt_id) or None,
            "name_roman": None,
            "name_th": name or None,
            "epc": row.get("epc") or None,
            "product": "LEASE" if order["order_type"] == "Leasing" else "CASH",
            "sales_lead": order["sales_lead"],
            "phone_masked": mask_phone(phone),
            "phone_e164": phone,
            "email_masked": mask_email(row.get("email_from")),
            "source_refs": [],
            "reason": "no money row in Odoo",
            "order": order,
        })
        if volt_id:
            seen.add(volt_stem(volt_id))
        verdicts.append({"volt_id": volt_id, "verdict": "landed",
                         "rule": None, "unmapped": unmapped})
    return records, verdicts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_normalise.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/crm_lead.py backend/tests/test_pipeline_normalise.py
git commit -m "feat(pipelines): crm.lead rows become book-shaped records, each saying Odoo knows of no money"
```

---

### Task 5: Two doors, one shape

**Files:**
- Create: `backend/app/pipelines/ingress.py`
- Test: `backend/tests/test_pipeline_ingress.py`

**Interfaces:**
- Consumes: `rules.Rules`; `app.integrations.odoo._config/_login/_execute`; `app.imports.decode_csv/read_xlsx/sniff_kind`.
- Produces: `ingress.from_odoo(rules, execute=None) -> list[dict]`, `ingress.from_upload(raw, filename, rules) -> list[dict]`, `ingress.PAGE = 500`.

- [ ] **Step 1: Write the failing test**

```python
"""Both doors hand normalise() the same thing."""
import io

from app.pipelines import ingress, rules as rules_mod

RULES = rules_mod.load()


class FakeExecute:
    """Stands in for odoo._execute. Records what was asked for."""

    def __init__(self, total=1200):
        self.total, self.calls = total, []

    def __call__(self, config, uid, model, method, args, kwargs=None):
        self.calls.append((model, method, kwargs or {}))
        if method == "search_count":
            return self.total
        offset = (kwargs or {}).get("offset", 0)
        limit = (kwargs or {}).get("limit", 500)
        return [{"id": str(i), "volt_id": "VL%07d" % i}
                for i in range(offset, min(offset + limit, self.total))]


def test_the_pull_pages_rather_than_asking_for_everything_at_once():
    fake = FakeExecute(total=1200)
    rows = ingress.from_odoo(RULES, execute=fake)
    assert len(rows) == 1200
    reads = [c for c in fake.calls if c[1] == "search_read"]
    assert [c[2]["offset"] for c in reads] == [0, 500, 1000]
    assert all(c[2]["limit"] == ingress.PAGE for c in reads)


def test_the_field_list_comes_from_the_rules_not_from_a_constant():
    fake = FakeExecute(total=1)
    ingress.from_odoo(RULES, execute=fake)
    asked = [c for c in fake.calls if c[1] == "search_read"][0][2]["fields"]
    mapped = {r["crm.lead field"] for r in RULES.field_map
              if r["crm.lead field"] not in ("—", "id")}
    assert mapped <= set(asked)


def test_a_dropped_csv_becomes_the_same_shape_as_a_pull():
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL0000143,0925423597,Order - Done\r\n").encode("utf-8-sig")
    rows = ingress.from_upload(raw, "x.csv", RULES)
    assert rows == [{"volt_id": "VL0000143", "phone": "0925423597",
                     "stage_name": "Order - Done"}]


def test_an_unknown_sheet_column_is_carried_not_dropped():
    raw = b"Volt ID,Something New\r\nVL0000143,keep me\r\n"
    rows = ingress.from_upload(raw, "x.csv", RULES)
    assert rows[0]["Something New"] == "keep me"


def test_the_upload_door_refuses_what_imports_py_already_refuses():
    from app.imports import UploadRefused
    try:
        ingress.from_upload(b"\xff\xfe\x00garbage", "x.csv", RULES)
    except UploadRefused:
        return
    raise AssertionError("a file that decodes as neither UTF-8 nor cp874 must refuse")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_ingress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.ingress'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The two doors. Both return list[dict] keyed by crm.lead FIELD NAME, so
normalise() cannot tell which one ran — that is what makes "the officer picks one"
a question for the screen rather than for the domain.

decode_csv and read_xlsx are imported from app.imports, never re-written: a second
CSV parser is ruling 36's second-pattern MAJOR, and that one already handles the
xlsx traps — shared strings, date serials, the 1904 epoch.
"""
import csv
import io

from .. import imports as imports_domain
from ..integrations import odoo

PAGE = 500


def _fields(rules):
    """Exactly what §2 of the rules file maps, plus the id. Adding a row to that
    table adds the field to the pull; no constant here to keep in step."""
    named = [r["crm.lead field"] for r in rules.field_map
             if r["crm.lead field"] not in ("—", "")]
    return sorted(set(named) | {"id"})


def from_odoo(rules, execute=None):
    execute = execute or odoo._execute
    config = odoo._config()
    uid = odoo._login(config)
    fields = _fields(rules)
    total = execute(config, uid, "crm.lead", "search_count", [[]])
    rows, offset = [], 0
    while offset < total:
        page = execute(config, uid, "crm.lead", "search_read", [[]],
                       {"fields": fields, "limit": PAGE, "offset": offset,
                        "order": "id"})
        if not page:
            break
        rows.extend(page)
        offset += len(page)
    return rows


def _header_map(rules):
    """Sheet column heading -> crm.lead field, from §2."""
    return {r["Sheet column"]: r["crm.lead field"] for r in rules.field_map
            if r["crm.lead field"] not in ("—", "")}


def from_upload(raw, filename, rules):
    """A dropped export of the "x" tab, in the same shape the pull produces.

    An unmapped column is KEPT under its own heading rather than dropped: the sheet
    holds eleven columns Odoo has no field for, and losing them at the door would
    make the upload strictly worse than the pull.
    """
    mapping = _header_map(rules)
    if imports_domain.sniff_kind(raw) == "XLSX":
        tabs = imports_domain.read_xlsx(raw)
        table = tabs[0]["rows"] if tabs else []
    else:
        _encoding, text = imports_domain.decode_csv(raw)
        table = list(csv.reader(io.StringIO(text)))
    if not table:
        return []
    header = [(c or "").strip() for c in table[0]]
    rows = []
    for line in table[1:]:
        if not any((c or "").strip() for c in line):
            continue
        row = {}
        for i, column in enumerate(header):
            if not column:
                continue
            value = line[i].strip() if i < len(line) and line[i] else ""
            row[mapping.get(column, column)] = value
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_ingress.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/ingress.py backend/tests/test_pipeline_ingress.py
git commit -m "feat(pipelines): two doors that hand the domain the same rows"
```

---

### Task 6: Write the run, batched, with the overwrite ledger

**Files:**
- Create: `backend/app/pipelines/writer.py`
- Test: `backend/tests/test_pipeline_writer.py`

**Interfaces:**
- Consumes: Task 4's records; `app.landing.start_run/finish_run/write_customer/write_order/resolved_customers`.
- Produces: `writer.write(conn, records, verdicts, batch=1000) -> dict` with keys `run_id`, `landed`, `rejected`, `overwrote`, `ledger`.

- [ ] **Step 1: Write the failing test**

```python
"""One run, batched, and honest about what it replaced."""
import pytest
from sqlalchemy import text

from app import landing, migrate
from app.pipelines import writer


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def _record(volt_id, **order):
    base = {"volt_id": volt_id, "customer_no": volt_id, "name_roman": None,
            "name_th": "ทดสอบ", "epc": "IPW", "product": "LEASE",
            "sales_lead": None, "phone_masked": "09x-xxx-3597",
            "phone_e164": "0925423597", "email_masked": None, "source_refs": [],
            "reason": "no money row in Odoo"}
    base["order"] = dict({"crm_id": "1", "order_type": "Leasing",
                          "order_status": "Order - Done", "loan_status": None,
                          "submit_date": None, "source_ref": []}, **order)
    return base


def test_a_run_lands_every_record_and_finishes_ok(schema):
    result = writer.write(schema, [_record("VL0000143"), _record("VL0000144")], [])
    assert result["landed"] == 2
    row = schema.execute(text("select source_system, status, row_counts "
                              "from landing.import_run where id=:i"),
                         {"i": result["run_id"]}).mappings().one()
    assert row["source_system"] == "ODOO"
    assert row["status"] == "OK"
    assert row["row_counts"]["landed"] == 2


def test_batching_lands_the_same_rows_as_one_at_a_time(schema):
    records = [_record("VL%07d" % i) for i in range(2500)]
    writer.write(schema, records, [], batch=1000)
    assert schema.execute(text("select count(*) from landing.customer")).scalar() == 2500


def test_replacing_a_sheet_value_is_recorded_with_both_values(schema):
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "name_th": "ชื่อจากชีต",
        "epc": "SLT", "product": "LEASE", "source_refs": []})
    landing.finish_run(schema, run, "OK")

    result = writer.write(schema, [_record("VL0000143")], [])
    assert result["overwrote"] == 1
    entry = [e for e in result["ledger"] if e["field"] == "epc"][0]
    assert entry == {"volt_id": "VL0000143", "field": "epc",
                     "sheet": "SLT", "odoo": "IPW"}


def test_an_odoo_blank_over_a_filled_sheet_value_is_in_the_ledger_too(schema):
    # The whole point of the ledger under the chosen precedence rule.
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "epc": "SLT",
        "product": "LEASE", "sales_lead": "Varunya", "source_refs": []})
    landing.finish_run(schema, run, "OK")

    result = writer.write(schema, [_record("VL0000143")], [])
    assert {"volt_id": "VL0000143", "field": "sales_lead",
            "sheet": "Varunya", "odoo": None} in result["ledger"]


def test_the_verdicts_travel_on_the_run_so_a_rejection_is_never_lost(schema):
    verdicts = [{"volt_id": "", "verdict": "rejected", "rule": "no_identity",
                 "unmapped": []},
                {"volt_id": "VL0000143", "verdict": "landed", "rule": None,
                 "unmapped": [["stage_name", "qualified_lead"]]}]
    result = writer.write(schema, [_record("VL0000143")], verdicts)
    meta = schema.execute(text("select meta from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    assert meta["rejected"] == {"no_identity": 1}
    assert meta["unmapped"] == [["stage_name", "qualified_lead"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../scripts/pg_local.sh start >/dev/null && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.writer'`

- [ ] **Step 3: Write minimal implementation**

```python
"""One import_run of source ODOO, written in batches, with a ledger of what it
replaced.

The ledger exists because of a decision taken on 2026-09-11: ODOO wins over SHEET,
which is landing._PRECEDENCE as it already stands. That was harmless while Odoo
contributed five rows that touched no sheet customer; with 34,401 it overlaps, so a
blank or zero in Odoo now replaces a real sheet value. The rule stands as chosen and
its cost is written down instead — per volt_id, per field, both values kept.
"""
import collections
import json

from sqlalchemy import text

from .. import landing

LEDGER_FIELDS = ("name_th", "name_roman", "epc", "product", "sales_lead",
                 "phone_e164", "email_masked", "customer_no")


def _sheet_rows(conn, volt_ids):
    """What SHEET holds today for the ids about to be written."""
    if not volt_ids:
        return {}
    rows = conn.execute(text(
        "select t.* from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'SHEET' and t.volt_id = any(:ids)"),
        {"ids": list(volt_ids)}).mappings().all()
    return {r["volt_id"]: dict(r) for r in rows}


def write(conn, records, verdicts, batch=1000):
    run = landing.start_run(conn, "ODOO")
    before = _sheet_rows(conn, [r["volt_id"] for r in records])

    ledger = []
    for record in records:
        sheet = before.get(record["volt_id"])
        if not sheet:
            continue
        for field in LEDGER_FIELDS:
            old, new = sheet.get(field), record.get(field)
            if old not in (None, "") and old != new:
                ledger.append({"volt_id": record["volt_id"], "field": field,
                               "sheet": old, "odoo": new})

    landed = 0
    for start in range(0, len(records), batch):
        for record in records[start:start + batch]:
            landing.write_customer(conn, run, "ODOO", record)
            order = dict(record.get("order") or {})
            order.setdefault("reason", record["reason"])
            landing.write_order(conn, run, "ODOO", record["volt_id"], order)
            landed += 1

    rejected = collections.Counter(v["rule"] for v in verdicts
                                   if v["verdict"] == "rejected" and v["rule"])
    unmapped = [u for v in verdicts for u in v.get("unmapped") or []]
    conn.execute(text("update landing.import_run set meta = cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"rejected": dict(rejected), "unmapped": unmapped,
                                   "overwrite_ledger": ledger,
                                   "reason": "no money row in Odoo"},
                                  ensure_ascii=False, default=str), "i": run})
    landing.finish_run(conn, run, "OK",
                       row_counts={"landed": landed, "rejected": sum(rejected.values()),
                                   "overwrote": len(ledger)})
    return {"run_id": run, "landed": landed, "rejected": sum(rejected.values()),
            "overwrote": len(ledger), "ledger": ledger}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_writer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/writer.py backend/tests/test_pipeline_writer.py
git commit -m "feat(pipelines): one run, batched, and a ledger of every sheet value Odoo replaced"
```

---

### Task 7: The endpoint

**Files:**
- Create: `backend/app/routers/pipelines.py`
- Modify: `backend/app/main.py` — import beside the other routers and `app.include_router(pipelines_router)` after line 1509
- Test: `backend/tests/test_pipeline_router.py`

**Interfaces:**
- Consumes: Tasks 1, 4, 5, 6.
- Produces: `POST /v1/pipelines/crm-lead:run` taking either `{"source": "odoo"}` as JSON or a multipart `file`; `GET /v1/pipelines/crm-lead/last-run`.

- [ ] **Step 1: Write the failing test**

```python
"""The endpoint refuses what it should and reports what it did."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_an_officer_may_not_run_the_pipeline():
    r = client.post("/v1/pipelines/crm-lead:run", json={"source": "odoo"},
                    headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert r.json()["message_th"]


def test_an_unknown_source_is_a_validation_problem_not_a_500():
    r = client.post("/v1/pipelines/crm-lead:run", json={"source": "telepathy"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/source"


def test_an_upload_runs_the_pipeline_and_reports_counts():
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL0000143,0925423597,Order - Done\r\n"
           ",,\r\n").encode("utf-8-sig")
    r = client.post("/v1/pipelines/crm-lead:run",
                    files={"file": ("x.csv", raw, "text/csv")},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code in (200, 503)      # 503 only when no DATABASE_URL is set
    if r.status_code == 200:
        body = r.json()
        assert body["landed"] == 1
        assert body["source"] == "upload"
        assert body["reason"] == "no money row in Odoo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_router.py -v`
Expected: FAIL — 404, the route does not exist

- [ ] **Step 3: Write minimal implementation**

```python
"""The crm.lead pipeline endpoint. Manager-only, and honest about which door ran."""
from fastapi import APIRouter, Body, File, Header, UploadFile

from .. import db, errors
from ..imports import UploadRefused
from ..integrations import odoo as odoo_client
from ..pipelines import crm_lead, ingress, rules as rules_mod, writer

router = APIRouter()


def _manager_only(role):
    if (role or "OFFICER").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only",
                             detail="Running an import is a Manager's act",
                             message_th="เฉพาะผู้จัดการนำเข้าข้อมูลได้",
                             error_id="DEBT-IAM-0403")


@router.post("/v1/pipelines/crm-lead:run")
async def run_crm_lead(file: UploadFile = File(default=None),
                       body: dict = Body(default=None),
                       x_volt_role: str = Header(default="OFFICER")):
    _manager_only(x_volt_role)
    try:
        rules = rules_mod.load()
    except rules_mod.RulesError as exc:
        raise errors.Problem(code="rules_unreadable", status=500,
                             title="The pipeline rules could not be read",
                             detail=str(exc),
                             message_th="อ่านกฎการนำเข้าไม่ได้",
                             error_id="DEBT-PIP-0500")

    if file is not None:
        raw = await file.read()
        try:
            raw_rows = ingress.from_upload(raw, file.filename, rules)
        except UploadRefused as exc:
            raise errors.validation_failed([{
                "pointer": exc.pointer, "code": "unreadable",
                "message": exc.message, "message_th": exc.message_th}])
        source = "upload"
    else:
        wanted = (body or {}).get("source")
        if wanted != "odoo":
            raise errors.validation_failed([{
                "pointer": "/source", "code": "invalid",
                "message": "source must be \"odoo\", or send a file",
                "message_th": "ต้องระบุ source เป็น odoo หรือแนบไฟล์"}])
        try:
            raw_rows = ingress.from_odoo(rules)
        except odoo_client.NotConfigured as exc:
            raise errors.integration_not_configured("Odoo", exc.missing)
        except odoo_client.OdooError as exc:
            raise errors.integration_unavailable("Odoo", str(exc))
        source = "odoo"

    records, verdicts = crm_lead.normalise(raw_rows, rules)
    if not db.configured():
        raise errors.Problem(code="database_required", status=503,
                             title="No database configured",
                             detail="The pipeline lands rows in the landing schema; "
                                    "set DATABASE_URL",
                             message_th="ต้องตั้งค่าฐานข้อมูลก่อนนำเข้า",
                             error_id="DEBT-PIP-0503")
    conn = db.connect()
    try:
        with conn.begin():
            result = writer.write(conn, records, verdicts)
    finally:
        conn.close()
    return {**result, "source": source, "read": len(raw_rows),
            "reason": "no money row in Odoo"}


@router.get("/v1/pipelines/crm-lead/last-run")
def last_run():
    from .. import landing
    if not db.configured():
        return {"run": None}
    conn = db.connect()
    try:
        return {"run": landing.last_run(conn, "ODOO")}
    finally:
        conn.close()
```

In `backend/app/main.py`, beside the other router imports:

```python
from .routers.pipelines import router as pipelines_router
```

and after line 1509:

```python
app.include_router(pipelines_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_router.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/pipelines.py backend/app/main.py backend/tests/test_pipeline_router.py
git commit -m "feat(pipelines): one endpoint, either door, Manager only"
```

---

### Task 8: The drop zone

**Files:**
- Create: `frontend/src/components/DropZone.jsx`
- Create: `frontend/src/components/DropZone.test.jsx`
- Modify: `frontend/src/api.js` — add `runCrmLeadPipeline`
- Modify: `frontend/src/screens/DataSourcesMigration.jsx:198-210` — wrap the existing input

**Interfaces:**
- Consumes: Task 7's endpoint.
- Produces: `<DropZone onFile={fn} accept=".csv,.xlsx" inputRef={ref} label={string} describedBy={id} />`; `api.runCrmLeadPipeline(fileOrNull)`.

- [ ] **Step 1: Write the failing test**

```jsx
import { render, screen, fireEvent } from '@testing-library/react'
import DropZone from './DropZone.jsx'

const file = new File(['Volt ID\nVL1'], 'x.csv', { type: 'text/csv' })

test('the real file input is still there, and still reachable', () => {
  render(<DropZone onFile={() => {}} label="เลือกไฟล์ชีต" />)
  const input = screen.getByLabelText('เลือกไฟล์ชีต')
  expect(input.tagName).toBe('INPUT')
  expect(input.type).toBe('file')
})

test('a dropped file is handed up', () => {
  const seen = []
  render(<DropZone onFile={(f) => seen.push(f)} label="เลือกไฟล์ชีต" />)
  fireEvent.drop(screen.getByTestId('dropzone'),
                 { dataTransfer: { files: [file], types: ['Files'] } })
  expect(seen).toEqual([file])
})

test('choosing through the input is handed up the same way', () => {
  const seen = []
  render(<DropZone onFile={(f) => seen.push(f)} label="เลือกไฟล์ชีต" />)
  fireEvent.change(screen.getByLabelText('เลือกไฟล์ชีต'), { target: { files: [file] } })
  expect(seen).toEqual([file])
})

test('dragging over says so without relying on colour alone', () => {
  render(<DropZone onFile={() => {}} label="เลือกไฟล์ชีต" />)
  const zone = screen.getByTestId('dropzone')
  fireEvent.dragEnter(zone, { dataTransfer: { types: ['Files'] } })
  expect(zone).toHaveAttribute('data-dragging', 'true')
  expect(screen.getByText(/วางไฟล์ที่นี่/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/DropZone.test.jsx`
Expected: FAIL — cannot resolve `./DropZone.jsx`

- [ ] **Step 3: Write minimal implementation**

```jsx
import { useRef, useState } from 'react'

/**
 * A drop target wrapped AROUND a real <input type="file">, never instead of one.
 * A div that accepts a drop and nothing else cannot be reached by keyboard and is
 * invisible to a screen reader, so the input stays and the drop is the addition.
 */
export default function DropZone({ onFile, accept = '.csv,.xlsx', inputRef, label,
                                   describedBy }) {
  const [dragging, setDragging] = useState(false)
  const ownRef = useRef(null)
  const ref = inputRef || ownRef

  const hasFiles = (ev) => Array.from(ev.dataTransfer?.types || []).includes('Files')

  return (
    <div
      data-testid="dropzone"
      data-dragging={dragging ? 'true' : 'false'}
      className={'dropzone' + (dragging ? ' dropzone--over' : '')}
      onDragEnter={(ev) => { if (hasFiles(ev)) { ev.preventDefault(); setDragging(true) } }}
      onDragOver={(ev) => { if (hasFiles(ev)) { ev.preventDefault(); setDragging(true) } }}
      onDragLeave={() => setDragging(false)}
      onDrop={(ev) => {
        ev.preventDefault()
        setDragging(false)
        const dropped = ev.dataTransfer?.files?.[0]
        if (dropped) onFile(dropped)
      }}
    >
      <label className="dropzone__label" htmlFor="pipeline-file">{label}</label>
      <input id="pipeline-file" ref={ref} type="file" accept={accept}
             className="ad-input" data-testid="import-file"
             aria-describedby={describedBy}
             onChange={(ev) => { const f = ev.target.files?.[0]; if (f) onFile(f) }} />
      <p className="dropzone__hint" aria-hidden={!dragging}>
        {dragging ? 'วางไฟล์ที่นี่' : 'ลากไฟล์มาวาง หรือเลือกไฟล์'}
      </p>
    </div>
  )
}
```

In `frontend/src/api.js`, beside the other integration calls:

```js
runCrmLeadPipeline: (file) => {
  if (!file) return post('/v1/pipelines/crm-lead:run', { source: 'odoo' })
  const body = new FormData()
  body.append('file', file)
  return request('/v1/pipelines/crm-lead:run', { method: 'POST', body })
},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/DropZone.test.jsx`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DropZone.jsx frontend/src/components/DropZone.test.jsx frontend/src/api.js frontend/src/screens/DataSourcesMigration.jsx
git commit -m "feat(data sources): drag and drop, wrapped around the file input rather than replacing it"
```

---

### Task 9: The whole thing, against the real contract

**Files:**
- Modify: `scripts/e2e_check.py` — add check 30
- Test: the existing suites, run in full

**Interfaces:**
- Consumes: every task above.
- Produces: e2e check 30, "an Odoo pipeline run lands identity rows and moves no money".

- [ ] **Step 1: Write the failing check**

Add to `scripts/e2e_check.py`, following the shape of the checks already there:

```python
def check_30_pipeline_lands_identity_without_moving_money(base):
    """The pipeline lands rows badged ODOO and the engine book does not move.

    proves: the 2026-09-11 design — Odoo holds no debt, so a run may add identities
            and must not add a collectable balance.
    """
    before = get(base, "/v1/migration/report")["counts"]
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL9999001,0912345678,Order - Done\r\n").encode("utf-8-sig")
    run = post_file(base, "/v1/pipelines/crm-lead:run", raw, "x.csv",
                    headers={"X-Volt-Role": "MANAGER"})
    after = get(base, "/v1/migration/report")["counts"]
    assert run["landed"] == 1, run
    assert run["reason"] == "no money row in Odoo", run
    assert after["engine_book"] == before["engine_book"], (before, after)
    assert after["registry"] == before["registry"] + 1, (before, after)
    return "landed %d, engine_book unchanged at %d" % (run["landed"], after["engine_book"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `scripts/run_prototype.sh`
Expected: check 30 FAILS — the route does not exist yet if tasks are run out of order; otherwise it passes and the whole suite is green

- [ ] **Step 3: Run every suite**

```bash
cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest -q
cd ../frontend && npx vitest run
cd .. && DATABASE_URL="postgresql+psycopg://postgres:@/volt_local?host=$HOME/.volt-postgres/data" scripts/run_prototype.sh
```

Expected: backend 569+, frontend 443+, e2e 30 of 30.

- [ ] **Step 4: Run the pipeline against real Odoo once**

```bash
cd backend && DATABASE_URL="postgresql+psycopg://postgres:@/volt_local?host=$HOME/.volt-postgres/data" \
  .venv/bin/python -c "
from app import db
from app.pipelines import crm_lead, ingress, rules, writer
r = rules.load()
rows = ingress.from_odoo(r)
records, verdicts = crm_lead.normalise(rows, r)
conn = db.connect()
with conn.begin():
    print(writer.write(conn, records, verdicts))
"
```

Expected: `landed` near 34,401, `rejected` grouped by rule, `overwrote` with a ledger to read. **Read the ledger before going further** — it is the measured cost of the precedence decision, and §6 of the rules file is one table edit away if it reads badly.

- [ ] **Step 5: Commit**

```bash
git add scripts/e2e_check.py
git commit -m "test(e2e): a pipeline run adds identities and no collectable balance"
```

---

## Self-Review

**Spec coverage.** §3 components → Tasks 1, 2–4, 5, 6, 7. §4 two doors → Task 5, screen in Task 8. §5 data flow → Task 6 (one run, one transaction). §6 volume → Task 6 batching, measured in Task 9 step 4. §7 precedence + ledger → Task 6. §8 error handling → every row of that table has a test: rules missing (Task 1), Odoo unreachable (Task 7), upload refused (Tasks 5 and 7), unmapped vocabulary (Tasks 2 and 6), rejection (Tasks 3 and 6). §9 testing → Tasks 1–9. §10 build order → task order.

**Gap found and closed:** the spec's §6 promised a filter on the Data sources screen so 34k rows are seen deliberately. Task 8 ships the drop zone but not that filter. It needs the run report on screen to be worth anything, so it belongs with the report rather than with the input — **Task 10 is deliberately deferred to a follow-up plan** once Task 9 step 4 has shown what a real run's ledger and counts look like. Nothing in Tasks 1–9 depends on it.

**Placeholders:** none. Every code step carries the code.

**Type consistency:** `normalise` returns `(records, verdicts)` in Tasks 4, 6, 7 and 9. `writer.write(conn, records, verdicts, batch=1000)` matches its call in Task 7. `rules.load()` returns `Rules` in Tasks 1, 2, 5, 7. `ingress.from_upload(raw, filename, rules)` matches Task 7's call. `volt_stem` is spelled the same in Tasks 3, 4 and the rules file's §1 key name.
