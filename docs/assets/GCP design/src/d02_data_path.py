"""Sheet 2 — the data path."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1170, "SHEET 2 — DATA PATH",
               "Two sources, one landing schema, one seam",
               "The 32 domain modules are untouched because book_source.load() returns exactly the dict "
               "shape that book.build() already consumes. Two sources land in one schema; one seam reads it.")
    c.header()

    # ================================================================
    # ROW 1 — stage 1 sources, stage 2 ingest, stage 3 store
    # groups: 160..436   channels 356..448, 1012..1072
    # ================================================================

    # ---- stage 1: sources ----
    c.group(52, 160, 320, 276, "Stage 1 · sources", "external", note="two, not one")
    c.node(68, 200, 288, 92, "New Order Master",
           ["418 customers — the sheet of record",
            "for the whole book"],
           "external", code="Google Sheet · 'sheet X'")
    c.node(68, 320, 288, 92, "Odoo UAT",
           ["sale.order + res.partner over JSON-RPC",
            "read-only · currently 5 orders"],
           "external", code="the second source", badge="READ-ONLY")

    # ---- stage 2: ingest ----
    c.group(432, 160, 580, 276, "Stage 2 · ingest", "api", note="one import_run each")
    c.node(448, 200, 548, 104, "import_master_sheet.py --to-postgres",
           ["Existing parse logic unchanged; a writer added. Reconciliation against",
            "the sheet's own pivots and the truncated-blocks report are carried",
            "into import_run rather than discarded."],
           "api", code="scripts/import_master_sheet.py", badge="1 IMPORT_RUN")
    c.node(448, 316, 548, 104, "integrations/odoo.py  sync()",
           ["Run by Cloud Run Job debt-odoo-sync, and also reachable at",
            "POST /v1/integrations/odoo:sync — Manager-only, externally",
            "unchanged."],
           "api", code="backend/app/integrations/odoo.py", badge="1 IMPORT_RUN")

    # ---- stage 3: store ----
    c.group(1072, 160, 556, 276, "Stage 3 · store", "data", note="Cloud SQL · Postgres")
    c.text(1088, 208, "schema  landing", size=12, fill="#a86412", weight=700)
    for i, table in enumerate(["customer", "order", "customer_block", "import_run"]):
        c.chip(1088, 224 + i * 48, 254, 42, table, "data")
    c.text(1358, 208, "schema  app", size=12, fill="#a86412", weight=700)
    c.chip(1358, 224, 254, 42, "session_state", "data")
    for i, ln in enumerate(["The only table in schema app.",
                            "Written by backend/app/session.py",
                            "— see stage 4, the seam."]):
        c.text(1358, 294 + i * 15, ln, size=11, fill="#6b7280")

    # ---- row 1 arrows ----
    c.arrow([(364, 246), (442, 250)], "parse", "external")
    c.arrow([(364, 366), (442, 368)], "read", "external")
    c.arrow([(1004, 252), (1082, 252)], "write", "api")
    c.arrow([(1004, 368), (1082, 380)], "write", "api")

    # ================================================================
    # ROW 2 — the precedence chain, and stage 4 the seam
    # groups: 496..766   channel 792..832
    # ================================================================

    c.group(52, 496, 740, 270, "The precedence chain", "data",
            note="ODOO → SNAPSHOT → SHEET")
    c.node(68, 536, 708, 66, "1 · rows from the CURRENT successful ODOO import_run", (),
           "domain", code="the normal case, once Odoo is the source of record", badge="ODOO")
    c.node(68, 610, 708, 66, "2 · else rows from the LAST PREVIOUS successful ODOO import_run", (),
           "data", code="the SNAPSHOT rung — has never existed in a deployed environment until now",
           badge="SNAPSHOT")
    c.node(68, 684, 708, 66, "3 · else the SHEET rows", (),
           "external", code="418 customers from New Order Master", badge="SHEET")

    # No group note here, and a short label: the right edge is where the
    # session.py -> app.session_state arrow climbs back into stage 3, and the
    # middle is where the landing rows come down.
    c.group(832, 496, 796, 270, "Stage 4 · the seam — two modules", "domain")
    c.node(848, 536, 372, 214, "backend/app/book_source.py",
           ["load() returns exactly the dict shape",
            "that book.build() already consumes",
            "today.",
            "",
            "That is why all 32 domain modules",
            "are untouched — nothing downstream",
            "knows the rows changed source.",
            "",
            "The precedence chain at left is",
            "applied here, not in the domain."],
           "domain", code="the seam", badge="NEW")
    c.node(1240, 536, 372, 214, "backend/app/session.py",
           ["Store keeps its for_current() /",
            "reset() / sessions() interface",
            "exactly as it is today.",
            "",
            "It swaps its in-memory dict for",
            "the app.session_state table,",
            "in schema app.",
            "",
            "No caller changes anywhere in",
            "the domain."],
           "domain", code="same interface, different storage")

    # ---- row 1 -> row 2, both directions ----
    c.arrow([(1180, 414), (1180, 530)], "rows", "data")
    c.arrow([(1590, 530), (1590, 270)], "writes", "domain")
    c.arrow([(786, 643), (842, 643)], "rows", "data")

    # ================================================================
    # ROW 3 — stage 5, the domain
    # ================================================================

    c.group(52, 796, 1576, 120, "Stage 5 · the domain, unchanged", "domain",
            note="32 modules · 158 endpoints · 11 screens")
    for i, (label, sub) in enumerate([("book.build()", "the assembler"),
                                      ("32 domain modules", "untouched"),
                                      ("158 endpoints", "FastAPI"),
                                      ("11 screens", "React")]):
        c.chip(150 + i * 380, 844, 240, 56, label, "domain", sub=sub)
        if i:
            c.arrow([(150 + i * 380 - 134, 872), (150 + i * 380 - 6, 872)], tone="domain", sw=1.5)

    # x=330 on the way down, not 270: 270 would land on the group's own label.
    c.arrow([(1034, 754), (1034, 780), (330, 780), (330, 838)], tone="domain")

    # ================================================================
    # ROW 4 — three notes
    # ================================================================

    c.note(52, 946, 500, 124,
           ["• Odoo writes landing.customer and landing.order rows and ZERO",
            "  landing.customer_block rows. sale.order and res.partner",
            "  contain nothing that answers leasing or tracking.",
            "• The schema states that boundary instead of hiding it",
            "  behind NULLs."],
           title="What Odoo cannot answer", tone="data")

    c.note(590, 946, 500, 124,
           ["• Each entry point — the sheet importer and the Odoo sync —",
            "  opens exactly one import_run.",
            "• One import run is one transaction.",
            "• A failed run leaves the previous run's rows serving: there",
            "  is no state in which half a book is visible."],
           title="Nothing half-written is ever visible", tone="api")

    c.note(1128, 946, 500, 124,
           ["• Today the Odoo cache is backend/var/odoo_snapshot.json,",
            "  which dies with the Cloud Run revision.",
            "• That is why the middle rung — the SNAPSHOT rung — has",
            "  never really existed in a deployed environment."],
           title="Why the middle rung has never existed", tone="infra")

    c.legend(52, c.h - 75, [("sources", "external"), ("ingest", "api"), ("store", "data"),
                            ("seam & domain", "domain"), ("today's runtime", "infra")])
    c.footer("pictures/GCP design/02-data-path.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
