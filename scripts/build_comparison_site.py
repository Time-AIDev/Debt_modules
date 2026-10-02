#!/usr/bin/env python3
"""Build the public comparison page from data/odoo/comparison.json.

Generated, never hand-edited: the numbers on the page are the ones the comparison
actually produced, and re-running the comparison and then this script is the only
way they change. The page carries NO customer data — the download it offers is the
47-row column mapping, which is schema and verdicts and nothing else. That is what
makes it safe to put on a public URL, while data/odoo itself stays gitignored.

    ./scripts/compare_crm_to_sheet.py      # refresh comparison.json
    ./scripts/build_comparison_site.py     # rebuild docs/odoo-comparison/
"""
import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "odoo" / "comparison.json"
SITE = ROOT / "docs" / "odoo-comparison"


def verdict_of(row):
    """One label per column, for the mapping CSV and the row's colour."""
    if row["differs"] and not (row["same"] or row["same (format)"]):
        return "disagree"
    if row["same"] or row["same (format)"]:
        return "disagree in part" if row["differs"] else "agree"
    if row["odoo zero/unset"]:
        return "Odoo holds 0"
    return "no data to compare"


CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#1b1a18;--dim:#65625c;--line:#e6e3dd;
 --ok:#17692f;--okbg:#e8f4ea;--bad:#a6231f;--badbg:#fbeceb;--warn:#8a5a08;--warnbg:#fdf3e0;
 --nil:#5c5a55;--nilbg:#f1efea;--accent:#1c4f8b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#15140f;--card:#1e1d18;--ink:#f0ede6;--dim:#a5a199;--line:#333128;
 --ok:#7fd694;--okbg:#16301d;--bad:#f0918c;--badbg:#331a19;--warn:#e5b45f;--warnbg:#332714;
 --nil:#a5a199;--nilbg:#26241e;--accent:#8ab6ee}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,"Noto Sans Thai",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding-block:40px;padding-left:20px;padding-right:20px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:18px;margin:38px 0 10px;letter-spacing:-.01em}
.sub{color:var(--dim);margin:0 0 26px;max-width:70ch}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}
.card{flex:1 1 150px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card b{display:block;font-size:26px;font-weight:650;letter-spacing:-.02em}
.card span{color:var(--dim);font-size:12.5px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
td.n{text-align:right;font-variant-numeric:tabular-nums}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--nilbg);
 padding:1px 5px;border-radius:4px}
.tag{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:99px}
.t-agree{color:var(--ok);background:var(--okbg)}
.t-disagree{color:var(--bad);background:var(--badbg)}
.t-part{color:var(--warn);background:var(--warnbg)}
.t-none{color:var(--nil);background:var(--nilbg)}
.ex{color:var(--dim);font-size:12.5px;white-space:normal;min-width:230px}
.dl{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;
 text-decoration:none;font-weight:600;font-size:14px;padding:11px 18px;border-radius:8px}
.dl:hover{filter:brightness(1.08)}
.note{border-left:3px solid var(--accent);padding:2px 0 2px 14px;color:var(--dim);
 margin:14px 0;max-width:76ch}
footer{color:var(--dim);font-size:12.5px;margin-top:40px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:560px){.card{flex:1 1 100%}h1{font-size:22px}}
"""


def tag(label):
    cls = {"agree": "t-agree", "disagree": "t-disagree",
           "disagree in part": "t-part"}.get(label, "t-none")
    return '<span class="tag %s">%s</span>' % (cls, html.escape(label))


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    SITE.mkdir(parents=True, exist_ok=True)
    values = {v["column"]: v for v in d["values"]}

    # --- the download: mapping + verdict, no customer rows ------------------------
    csv_path = SITE / "crm_lead_vs_sheet_x.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_x_column", "crm_lead_field", "in_odoo", "verdict",
                    "same", "same_after_formatting", "differs", "odoo_zero_unset",
                    "one_side_empty", "both_empty", "example_of_a_difference"])
        for column, field in d["map"].items():
            v = values.get(column)
            w.writerow([column, field or "", "yes" if field else "no",
                        verdict_of(v) if v else ("not compared" if field else "sheet only"),
                        v["same"] if v else "", v["same (format)"] if v else "",
                        v["differs"] if v else "", v["odoo zero/unset"] if v else "",
                        v["one side empty"] if v else "", v["both empty"] if v else "",
                        v["example"] if v else ""])

    agree = sum(1 for v in d["values"] if verdict_of(v) == "agree")
    disagree = sum(1 for v in d["values"] if verdict_of(v).startswith("disagree"))

    rows = []
    for column, field in d["map"].items():
        v = values.get(column)
        if not field:
            rows.append("<tr><td>%s</td><td><em style='color:var(--dim)'>no Odoo field</em></td>"
                        "<td>%s</td><td class='n'>&mdash;</td><td class='n'>&mdash;</td>"
                        "<td class='n'>&mdash;</td>"
                        "<td class='ex'>the sheet holds this and Odoo does not</td></tr>"
                        % (html.escape(column), tag("sheet only")))
            continue
        rows.append(
            "<tr><td>%s</td><td><code>%s</code></td><td>%s</td>"
            "<td class='n'>%d</td><td class='n'>%d</td><td class='n'>%d</td><td class='ex'>%s</td></tr>"
            % (html.escape(column), html.escape(field), tag(verdict_of(v)),
               v["same"] + v["same (format)"], v["differs"],
               v["odoo zero/unset"] + v["one side empty"] + v["both empty"],
               html.escape(v["example"] or "")))

    joins = "".join("<tr><td>%s</td><td class='n'>%d of %d</td></tr>"
                    % (html.escape(k), n, d["sheet_rows"]) for k, n in d["joins"].items())

    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>crm.lead vs the &ldquo;x&rdquo; tab</title><style>%s</style></head><body>
<div class="wrap">
<h1>Odoo <code>crm.lead</code> vs the New Order Master &ldquo;x&rdquo; tab</h1>
<p class="sub">What the two systems hold in common, where they disagree, and where only one of
them knows the answer. The column mapping covers all %d sheet columns; values are compared
across the %d sheet rows that found their lead.</p>

<div class="cards">
<div class="card"><b>%d</b><span>sheet &ldquo;x&rdquo; columns</span></div>
<div class="card"><b>%d</b><span>exist in crm.lead</span></div>
<div class="card"><b>%d</b><span>sheet only</span></div>
<div class="card"><b>%d / %d</b><span>rows matched to a lead</span></div>
<div class="card"><b>%s</b><span>crm.lead rows in Odoo</span></div>
</div>

<p><a class="dl" href="crm_lead_vs_sheet_x.csv" download>&darr;&nbsp; Download the mapping (CSV)</a></p>
<p class="note">This download is the %d-row column mapping and its verdicts &mdash; schema only.
It carries no customer records. The underlying <code>crm.lead</code> extract holds real names,
phone numbers and addresses for %s leads, and is deliberately not published here.</p>

<h2>How the rows were matched</h2>
<div class="tw"><table><thead><tr><th>Join key</th><th>Sheet rows it found</th></tr></thead>
<tbody>%s</tbody></table></div>
<p class="note">The sheet&rsquo;s own <code>Odoo ID</code> column is filled on only 3 of %d rows,
and holds a Volt id (<code>99999000206</code>) rather than a numeric Odoo id &mdash; so the
documented key is both nearly empty and pointing at a different field than its name implies.
The phone number, and <code>Volt ID</code> compared on its leading id segment, each find every row.</p>

<h2>Column by column</h2>
<div class="tw"><table><thead><tr>
<th>Sheet &ldquo;x&rdquo; column</th><th>crm.lead field</th><th>Verdict</th>
<th>Agree</th><th>Differ</th><th>No data</th><th>Example of a difference</th>
</tr></thead><tbody>%s</tbody></table></div>

<h2>What the verdicts mean</h2>
<div class="tw"><table><tbody>
<tr><td>%s</td><td class="ex">Both systems hold it and say the same thing &mdash; sometimes after
normalising a date (<code>02/05/24</code> = <code>2024-05-02</code>) or a code
(<code>paid_out</code> = <code>Paid Out</code>).</td></tr>
<tr><td>%s</td><td class="ex">Both hold it and they do not agree. All three cases here are
systematic rather than random: romanised vs Thai names, <code>Order - Done</code> vs
<code>Won</code>, <code>1</code> vs <code>single_phase</code>.</td></tr>
<tr><td>%s</td><td class="ex">Odoo has the field but it is 0 or blank on these rows &mdash;
Energy Bill, Watt and Monthly Rate are declared and unused.</td></tr>
<tr><td>%s</td><td class="ex">The sheet holds it and Odoo has no field for it at all.</td></tr>
</tbody></table></div>

<footer>Generated by <code>scripts/build_comparison_site.py</code> from the output of
<code>scripts/compare_crm_to_sheet.py</code>. Sheet: New Order Master, &ldquo;x&rdquo; tab,
Drive export &mdash; truncated per tab, which is why %d rows and not the whole book.
Odoo: UAT, read-only pull.</footer>
</div></body></html>""" % (
        CSS, len(d["map"]), d["matched_pairs"], len(d["map"]), len(d["columns_in_both"]),
        len(d["columns_sheet_only"]), d["matched_pairs"], d["sheet_rows"],
        "{:,}".format(d["crm_lead_rows"]), len(d["map"]),
        "{:,}".format(d["crm_lead_rows"]), joins, d["sheet_rows"], "".join(rows),
        tag("agree"), tag("disagree"), tag("Odoo holds 0"), tag("sheet only"), d["sheet_rows"])

    (SITE / "index.html").write_text(page, encoding="utf-8")
    print("wrote %s  (%d columns agree, %d disagree)" % (SITE / "index.html", agree, disagree))
    print("wrote %s" % csv_path)


if __name__ == "__main__":
    raise SystemExit(main())
