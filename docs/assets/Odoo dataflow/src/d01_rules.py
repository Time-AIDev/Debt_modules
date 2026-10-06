"""Sheet 01 — the rules themselves, measured rather than assumed."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 944, "ODOO DATAFLOW — 01",
               "The rules, the evidence for each, and which of them are wired",
               "Every row here was measured on 2026-09-11 against the 58 \"x\"-tab rows in the Drive "
               "export and the 34,401 crm.lead rows in Odoo UAT. None of it is assumed — but Rule 1 is measured only, and the pipeline does not consume it yet.")
    c.header()

    # ---- join keys --------------------------------------------------------------
    c.group(52, 160, 500, 316, "Rule 1 — how a lead is matched to a sheet row", "domain")
    JOINS = [("Phone → phone / mobile", "58 of 58", "domain"),
             ("Volt ID → volt_id, leading segment", "58 of 58", "domain"),
             ("Volt ID → volt_id, exact", "0 of 58", "external"),
             ("\"Odoo ID\" → crm.lead.id", "0 of 58", "external"),
             ("\"Odoo ID\" → volt_id", "3 of 58", "external")]
    for i, (label, hits, tone) in enumerate(JOINS):
        c.node(76, 204 + i * 54, 452, 44, label, [], tone, badge=hits)

    c.note(52, 492, 500, 120, [
        "• NOT YET WIRED. The pipeline joins on exact volt_id only — row 3.",
        "• The sheet's own \"Odoo ID\" column is filled on 3 of 58 rows,",
        "  and holds 99999000206 — a Volt id, not a numeric Odoo id.",
        "• The \"Peak ID\" column holds Thai customer NAMES on all 58 rows.",
        "• So the column that exists to join the two systems does neither.",
    ], title="Measured — and two traps in the sheet itself", tone="external")

    # ---- translations -----------------------------------------------------------
    c.group(596, 160, 512, 316, "Rule 2 — translate before comparing", "data")
    T = [("dates", "02/05/24", "2024-05-02"),
         ("month/year", "05/24", "2024-05"),
         ("codes", "paid_out", "Paid Out"),
         ("stage", "Won", "Order - Done"),
         ("phase", "single_phase", "1")]
    for i, (kind, left, right) in enumerate(T):
        y = 204 + i * 54
        c.chip(620, y, 92, 44, kind, "data")
        c.node(724, y, 150, 44, left, [], "neutral")
        c.arrow([(882, y + 22), (906, y + 22)], tone="data", sw=1.5)
        c.node(914, y, 170, 44, right, [], "domain")

    c.note(596, 492, 512, 120, [
        "• Compared as raw strings, dates called 54 of 58 rows a disagreement",
        "  when the two systems named the same day. paid_out vs Paid Out was",
        "  a second false positive.",
        "• A rule that manufactures conflicts is worse than no rule.",
    ], title="Why this rule exists", tone="refusal")

    # ---- the verdict ------------------------------------------------------------
    c.group(1152, 160, 476, 316, "Rule 3 — what the 47 columns did", "domain")
    V = [("agree", "13", "domain"), ("agree once translated", "16", "domain"),
         ("genuinely disagree", "3", "external"),
         ("Odoo declares it, never fills it", "10", "data"),
         ("sheet only, no Odoo field", "11", "neutral")]
    for i, (label, n, tone) in enumerate(V):
        c.node(1176, 204 + i * 54, 428, 44, label, [], tone, badge=n)

    c.note(1152, 492, 476, 120, [
        "• romanised vs Thai names  (Runjit / ลูกค้าทดสอบ 0005)",
        "• Order - Done vs Won",
        "• 1 vs single_phase",
        "All three are systematic, so all three are translations,",
        "not conflicts. Nothing here is dirty data.",
    ], title="The three real disagreements", tone="external")

    # ---- rejection --------------------------------------------------------------
    c.group(52, 632, 1056, 152, "Rule 4 — what the pipeline refuses to land", "refusal")
    R = [("no volt_id and no phone", ["nothing to join on, and nothing", "to identify the person by"]),
         ("a volt_id shaped like neither", ["not 99999000032_… and not VL0000143", "— the id is not an id"]),
         ("duplicate volt_id in one run", ["the later row wins and the", "earlier is reported, never dropped silently"])]
    for i, (title, lines) in enumerate(R):
        c.node(76 + i * 340, 676, 316, 86, title, lines, "refusal")

    c.note(1152, 632, 476, 152, [
        "• Every rejected row is counted, with the rule that",
        "  rejected it, on import_run.meta.",
        "• A pipeline that drops rows quietly is the defect this",
        "  whole exercise exists to remove — the same reason",
        "  book_source refuses rather than falling back when a",
        "  configured database has gone away.",
    ], title="Rejection is reported, never silent", tone="refusal")

    c.legend(52, 826, [("holds / agrees", "domain"), ("translate", "data"),
                       ("disagrees", "external"), ("refusal", "refusal")])
    c.footer("pictures/Odoo dataflow/src/d01_rules.py  ·  measured 2026-09-11, uid 299, read-only",
             right="Volt Debt Collection — Odoo dataflow")
    return c
