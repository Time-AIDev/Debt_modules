#!/usr/bin/env python3
"""Write data/odoo/README.md from the manifest the pull left behind.

Separate from the pull so it can be re-run after a partial pull without touching
Odoo, and so the folder always explains itself to whoever opens it next — the
folder is gitignored, so this README is the only thing travelling with the data.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "odoo"

GROUPS = {
    "renewable.energy.order": "The real Volt order book — one row per project, each with a volt_id",
    "invoice.installment.line": "The installment schedule: amount, due date, paid flag, state",
    "customer.document": "Documents attached to a customer or order (the file blobs are dropped)",
    "account.move": "Journal entries and invoices",
    "account.move.line": "Journal items",
    "account.bank.statement.line": "Bank statement lines — incoming money",
    "res.partner": "Contacts. Curated field list: the model has ~150 fields and 128k rows",
    "crm.lead": "Pipeline leads. Curated field list, same reason",
    "volt.lease.payment": "Lease PRICING matrix (package x size x phase x months x DP%), not a ledger",
    "volt.lease.line": "Lease pricing lines that the matrix hangs off",
    "sale.order": "Odoo's stock sale orders — 5 draft test rows on this instance",
}


def main():
    manifest = json.loads((OUT / "manifest.json").read_text())
    lines = ["# data/odoo — a read-only CSV pull from Odoo UAT", "",
             "Pulled by `scripts/pull_odoo_csv.py` at %s (login uid %s)."
             % (manifest["source"]["pulled_at"], manifest["source"]["login_uid"]),
             "", "**Gitignored, and it should stay that way.** Phone, mobile, fax and email are",
             "masked at pull time (the same masks the sheet importer uses), but names, site",
             "addresses, tax ids and amounts are exactly as Odoo returned them.", "",
             "| File | Rows | Cols | Size | What it is |", "|---|---|---|---|---|"]
    total = 0
    for entry in manifest["models"]:
        model = entry["model"]
        if entry.get("error"):
            lines.append("| `%s` | — | — | — | REFUSED: %s |" % (model, entry["error"][:60]))
            continue
        total += entry["rows_written"]
        lines.append("| `%s.csv` | %s | %d | %s | %s |" % (
            model, "{:,}".format(entry["rows_written"]), entry["columns"],
            _human(entry["bytes"]), GROUPS.get(model, "")))
    lines += ["", "**%s rows across %d files.**" % ("{:,}".format(total), len(manifest["models"])), "",
              "## Conventions", "",
              "- A many2one is one column, `id|label`. An x2many is a space-separated id list.",
              "- Binary fields are dropped (they are base64 blobs); the manifest names them per model.",
              "- Fields Odoo refused to read in a batch are named in `manifest.json` under",
              "  `unreadable_fields`, with the error. They are broken computes on this instance,",
              "  not access rules — everything else in the model still landed.", ""]
    broken = {m["model"]: m.get("unreadable_fields") or {}
              for m in manifest["models"] if m.get("unreadable_fields")}
    if broken:
        lines += ["## Fields this instance could not read", ""]
        for model, fields in broken.items():
            lines.append("- `%s`: %s" % (model, ", ".join("`%s`" % f for f in fields)))
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT / "README.md")


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


if __name__ == "__main__":
    raise SystemExit(main())
