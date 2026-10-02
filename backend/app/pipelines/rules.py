"""The rules file, parsed. docs/odoo-comparison/odoo_compare.md is the source of
truth; this module is only the reader.

Markdown tables and not YAML for the same reason import_master_sheet.py reads
markdown tables: the file has to stay readable by the person who edits it, and a
table is the one format that is both. A table is identified by its header row, so
the headers below are a contract with the document — rename a column there and the
load refuses by name rather than silently returning an empty section.
"""
from pathlib import Path

# Two layouts, one file — the same pattern app/imports.py uses for the sheet
# importer. In a checkout the rules sit at <root>/docs/odoo-comparison/; the
# container is built from `backend/` alone (`gcloud run deploy --source backend`),
# so scripts/deploy_gcp.sh stages the file into backend/docs/... and the reader finds
# it there. Without the second candidate the crm.lead pull died with
# "rules_unreadable" on staging while every local run was green (2026-09-21).
RULES_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "docs" / "odoo-comparison" / "odoo_compare.md",
    Path(__file__).resolve().parents[2] / "docs" / "odoo-comparison" / "odoo_compare.md",
)
RULES_PATH = RULES_CANDIDATES[0]


def resolve_path():
    """The first candidate that exists. Refuses by name when none does — a pipeline
    on rules nobody can see is the problem this module exists to remove."""
    for candidate in RULES_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RulesError("the rules file is missing — looked in: %s"
                     % ", ".join(str(c) for c in RULES_CANDIDATES))

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
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise RulesError("the rules file is missing: %s" % path)
    else:
        path = resolve_path()
    found = {tuple(h): r for h, r in tables(path.read_text(encoding="utf-8"))}
    sections = {}
    for name, header in HEADERS.items():
        if header not in found:
            raise RulesError("%s: no table with header %r" % (path.name, " | ".join(header)))
        sections[name] = found[header]
    return Rules(sections)
