"""Sheet 00 — the crm.lead pipeline, ingress to screen."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 920, "ODOO DATAFLOW — 00",
               "crm.lead into the book, by whichever door the officer chooses",
               "Two ingress paths that produce the same raw rows, one rules file that decides what happens "
               "to them, and one import_run that says what landed, what it refused, and what it could not measure.")
    c.header()

    # ---- the two doors ----------------------------------------------------------
    c.group(52, 160, 372, 250, "Ingress — the officer picks one", "client")

    c.node(76, 204, 324, 78, "Drag and drop", [
        "A .csv or .xlsx of the sheet's \"x\" tab,",
        "dropped on the Data sources screen"],
        "client", code="frontend/…/DataSourcesMigration.jsx")
    c.node(76, 296, 324, 90, "Pull directly from Odoo", [
        "search_read on crm.lead, paged 500,",
        "fields taken from the rules file",
        "34,401 rows · 26,110 with a volt_id"],
        "client", code="pipelines/ingress.py")

    c.note(52, 424, 372, 86, [
        "• The file input STAYS. The drop zone wraps it,",
        "  so keyboard and screen-reader users keep a",
        "  real <input type=\"file\"> — never a div.",
    ], title="Drag and drop is an addition", tone="refusal")

    c.note(52, 526, 372, 100, [
        "• decode_csv / read_xlsx are imported from",
        "  imports.py, never re-written. A second CSV",
        "  parser is ruling 36's second-pattern MAJOR,",
        "  and that one already handles xlsx date serials.",
    ], title="No second parser", tone="refusal")

    # ---- the shared raw shape ---------------------------------------------------
    c.node(468, 240, 208, 118, "raw rows", [
        "list[dict], identical from",
        "either door — normalise()",
        "never learns which one ran",
    ], "neutral", badge="1 shape")
    c.arrow([(404, 243), (440, 243), (440, 282), (464, 282)], tone="client", sw=1.5)
    c.arrow([(404, 341), (440, 341), (440, 312), (464, 312)], tone="client", sw=1.5)

    # ---- the rules --------------------------------------------------------------
    c.node(468, 424, 208, 132, "odoo_compare.md", [
        "The rules, as markdown",
        "tables — parsed, not just",
        "read. Edit the doc and the",
        "pipeline behaves differently.",
    ], "data", code="docs/odoo-comparison/")
    c.arrow([(572, 420), (572, 366)], label="loaded by rules.py", tone="data", sw=1.5,
            label_at=0, label_dy=-9)

    # ---- normalise --------------------------------------------------------------
    c.group(720, 160, 404, 466, "normalise(rows, rules) — a pure function", "domain")
    BANDS = [
        ("identity", ["volt_id cleaned; Odoo's literal \"New\" is a", "placeholder, not an id — the phone carries it"]),
        ("map", ["47 sheet columns → 36 crm.lead", "fields; 11 have no Odoo field"]),
        ("vocab", ["Won → Order - Done", "single_phase → 1"]),
        ("dates", ["02/05/24 → 2024-05-02", "05/24 → 2024-05"]),
        ("codes", ["paid_out → Paid Out"]),
        ("verdict", ["landed · rejected · overwrote", "— one per row, none silent"]),
    ]
    for i, (name, lines) in enumerate(BANDS):
        c.node(744, 204 + i * 70, 356, 58, name, lines, "domain")

    c.arrow([(680, 299), (716, 299)], tone="domain", sw=1.6)

    # ---- landing ----------------------------------------------------------------
    c.group(1168, 160, 460, 250, "One import_run of source ODOO", "data")
    c.node(1192, 204, 412, 76, "landing.customer / landing.order", [
        "Written through the EXISTING writers, batched",
        "with executemany — 34k single statements is 34k round trips",
    ], "data", code="backend/app/landing.py")
    c.node(1192, 292, 412, 100, "run.meta", [
        "row_counts · rejected, with the rule that rejected them",
        "overwrite ledger — matched on the WHOLE volt_id today,",
        "which is why it reads 0. §1 of the rules is not wired yet.",
    ], "data")
    c.arrow([(1128, 299), (1164, 299)], label="one transaction", tone="data", sw=1.6)

    # ---- out to the app ---------------------------------------------------------
    c.node(1168, 448, 460, 84, "book_source.load()", [
        "Reads the landing schema exactly as it does today.",
        "Nothing in the 32 domain modules changes shape.",
    ], "domain", code="backend/app/book_source.py")
    c.arrow([(1398, 414), (1398, 444)], tone="data", sw=1.6)

    c.node(1168, 556, 460, 70, "Every screen, badged ODOO", [
        "data_source tells a reviewer real from invented",
    ], "client")
    c.arrow([(1398, 536), (1398, 552)], tone="domain", sw=1.6)

    # ---- the honest ending ------------------------------------------------------
    c.note(720, 648, 908, 122, [
        "• All 34,401 rows land as IDENTITY, each carrying reason \"no money row in Odoo\".",
        "• They appear in the registry and the migration report. The filterable Odoo view is not built.",
        "• They are absent from Today, arrears and NPL — because Odoo holds no debt to collect:",
        "  every ren order is stage `new`, all 79 installments are draft and unpaid, and of 236",
        "  account.move rows exactly one is a customer invoice. The absence is the fact.",
    ], title="What 34,401 rows actually buy you", tone="refusal")

    c.note(52, 648, 640, 122, [
        "• Chosen 2026-09-11: Odoo wins — landing._PRECEDENCE as it already stands.",
        "• Harmless at 5 rows. With 34k it overlaps: 58 of 58 sheet rows match a lead by phone,",
        "  so a blank or zero in Odoo now replaces a real sheet value — and Energy Bill, Watt",
        "  and Monthly Rate are 0 on every Odoo row we measured.",
        "• The overwrite ledger reads 0, but it compares WHOLE volt_ids, which the two systems",
        "  never share. That is no measurement, not no harm. §1's keys are not wired in.",
    ], title="Precedence, and its price", tone="external")

    c.legend(52, 812, [("officer / UI", "client"), ("rules + data", "data"),
                       ("pure domain", "domain"), ("refusal", "refusal"),
                       ("consequence", "external")])
    c.footer("pictures/Odoo dataflow/src/d00_dataflow.py  ·  rebuild: ./src/build.sh",
             right="Volt Debt Collection — Odoo dataflow")
    return c
