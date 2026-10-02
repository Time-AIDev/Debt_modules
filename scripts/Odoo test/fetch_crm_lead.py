#!/usr/bin/env python3
"""Fetch every field of Odoo crm.lead, UNMASKED, into data/odoo/crm.lead/.

WARNING (2026-10-01): a run of this script once produced a 450-row snapshot that
was NOT the full model (live Odoo holds 34k+ active leads; the directory missed,
for example, crm.lead 163354). Never use its output as the Odoo census — for a
consistency answer read live Odoo (`scripts/reconcile_app_odoo_sheet.py`) or the
full pull (`scripts/pull_odoo_csv.py`), and check the row count it prints.

Writes:
  crm.lead.raw.jsonl   one lead per line, exactly as search_read returned it
  crm.lead.csv         the same rows flattened (many2one -> "id|label", x2many -> "1 2 3")
  fields.json          fields_get for the model (the CSV header's schema)

No masking: real names, phones, emails, addresses and binaries (base64). data/odoo/
is gitignored — keep it that way and don't copy these files out.

    backend/.venv/bin/python "scripts/Odoo test/fetch_crm_lead.py"               # active leads
    backend/.venv/bin/python "scripts/Odoo test/fetch_crm_lead.py" --archived    # + archived
    backend/.venv/bin/python "scripts/Odoo test/fetch_crm_lead.py" --limit 50    # smoke test
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.integrations import odoo  # noqa: E402

odoo.TIMEOUT = 120.0   # the app's 8 s is too short for 200 rows x 401 fields

MODEL = "crm.lead"
OUT = ROOT / "data" / "odoo" / MODEL
PAGE = 200


def cell(value):
    if value is False or value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], str):
            return "%d|%s" % tuple(value)
        return " ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


def read_page(cfg, uid, names, ids, ctx, tries=0):
    """Every row of `ids`. Network trouble: split the batch in half and read both
    halves. A computed field that raises on the batch: drop that field and say so."""
    while True:
        try:
            return names, odoo._execute(cfg, uid, MODEL, "read", [ids], {
                "fields": names, "context": ctx})
        except httpx.TransportError as exc:
            if tries >= 6:
                raise
            print("  %s at id %d (%d ids), splitting" % (type(exc).__name__, ids[0], len(ids)),
                  file=sys.stderr, flush=True)
            time.sleep(2 * (tries + 1))
            half = max(1, len(ids) // 2)
            names, left = read_page(cfg, uid, names, ids[:half], ctx, tries + 1)
            if half == len(ids):
                return names, left
            names, right = read_page(cfg, uid, names, ids[half:], ctx, tries + 1)
            return names, left + right
        except Exception:
            bad = []
            for f in names:
                try:
                    odoo._execute(cfg, uid, MODEL, "read", [ids], {"fields": [f], "context": ctx})
                except Exception as exc:
                    bad.append(f)
                    print("  dropped unreadable field %s: %s" % (f, str(exc).splitlines()[0][:100]),
                          file=sys.stderr)
            if not bad:
                raise
            names = [f for f in names if f not in bad]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="stop after N rows (smoke test)")
    ap.add_argument("--archived", action="store_true", help="include archived leads")
    args = ap.parse_args()

    assert cell([7, "Won"]) == "7|Won" and cell([1, 2]) == "1 2" and cell(False) == ""

    cfg = odoo._config()
    uid = odoo._login(cfg)
    ctx = {"active_test": not args.archived}
    fields = odoo._execute(cfg, uid, MODEL, "fields_get", [], {"attributes": ["string", "type", "store"]})
    names = sorted(fields, key=lambda f: (f != "id", f))
    # ids first, then read by id: offset paging skips rows when leads change mid-run.
    ids = odoo._execute(cfg, uid, MODEL, "search", [[]], {"order": "id", "context": ctx})
    ids = ids[:args.limit] if args.limit else ids
    total = len(ids)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fields.json").write_text(json.dumps(fields, ensure_ascii=False, indent=1))
    header, rows = list(names), 0
    # utf-8-sig so Excel opens the Thai text correctly. A field dropped mid-run stays
    # in the header and is blank from that point on.
    with open(OUT / "crm.lead.raw.jsonl", "w", encoding="utf-8") as raw, \
            open(OUT / "crm.lead.csv", "w", newline="", encoding="utf-8-sig") as handle:
        w = csv.writer(handle)
        w.writerow(header)
        for start in range(0, total, PAGE):
            names, page = read_page(cfg, uid, names, ids[start:start + PAGE], ctx)
            for r in page:   # a lead deleted mid-run simply isn't in the page
                raw.write(json.dumps(r, ensure_ascii=False) + "\n")
                w.writerow([cell(r.get(f)) for f in header])
            rows += len(page)
            print("  %d/%d" % (start + len(ids[start:start + PAGE]), total), file=sys.stderr, flush=True)
    print("%d rows x %d columns -> %s" % (rows, len(header), OUT))
    if len(names) < len(header):
        print("dropped fields: %s" % ", ".join(sorted(set(header) - set(names))))


if __name__ == "__main__":
    main()
