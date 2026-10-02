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
    assert len(loaded.field_map) == 49
    assert len(loaded.vocab) == 5
    assert len(loaded.normalisers) == 7
    # §5 grew a fourth rule on 2026-09-11: the literal "New" placeholder,
    # which 23,514 of 34,338 live leads carry — and a fifth on 2026-09-25:
    # date_unreadable, a date that is not a real calendar date.
    assert len(loaded.rejections) == 5
    assert loaded.precedence == [{"Field group": "all", "Winner": "odoo",
                                  "Decided": "2026-09-11"}]


def test_a_missing_rules_file_refuses_rather_than_defaulting(tmp_path):
    with pytest.raises(rules_mod.RulesError) as exc:
        rules_mod.load(tmp_path / "nope.md")
    assert "nope.md" in str(exc.value)


def test_the_rules_resolve_in_the_container_layout_too(tmp_path, monkeypatch):
    """The image is built from backend/ alone, so the reader carries two candidates:
    the checkout's docs/odoo-comparison and the staged backend/docs/odoo-comparison
    (scripts/deploy_gcp.sh copies it in). 2026-09-21: staging's crm.lead pull exited
    "rules_unreadable" because only the first layout was ever looked at."""
    missing = tmp_path / "not-here" / "odoo_compare.md"
    staged = tmp_path / "backend" / "docs" / "odoo-comparison" / "odoo_compare.md"
    staged.parent.mkdir(parents=True)
    staged.write_text(rules_mod.RULES_CANDIDATES[0].read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_CANDIDATES", (missing, staged))
    assert rules_mod.resolve_path() == staged
    assert rules_mod.load().joins, "the staged file is read, not just found"


def test_a_missing_rules_file_names_every_place_it_looked(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_mod, "RULES_CANDIDATES", (tmp_path / "nope.md",))
    with pytest.raises(rules_mod.RulesError) as exc:
        rules_mod.resolve_path()
    assert "looked in" in str(exc.value)
