"""Sheet 3 — the landing and app schemas."""
from hld_lib import Canvas, MONO, MUTED, FAINT


NB = "\u00a0"  # SVG collapses runs of ordinary spaces; these columns must not move


def cols(rows, npad=21, tpad=13):
    """Column lines, monospace-aligned. Each row is (pk, name, type[, extra])."""
    out = []
    for r in rows:
        pk, name, typ = r[0], r[1], r[2]
        extra = r[3] if len(r) > 3 else ""
        line = ("PK " if pk else "   ") + name.ljust(npad) + typ.ljust(tpad) + extra
        out.append(line.replace(" ", NB))
    return out


def build():
    c = Canvas(1680, 890, "SHEET 3 — SCHEMA",
               "landing and app, shaped like New Order Master",
               "data_source sits inside the primary key, so a SHEET row and an ODOO row for the "
               "same volt_id coexist rather than overwrite.")
    c.header()

    def table(x, y, w, title, rows, tone, badge=None, code=None, npad=21, tpad=13):
        lines = cols(rows, npad, tpad)
        h = 14 * len(lines) + 62
        c.node(x, y, w, h, title, (), tone, code=code, badge=badge)
        ty = y + 44
        for ln in lines:
            c.text(x + 12, ty, ln, size=10.5, fill=MUTED, font=MONO)
            ty += 14
        return h

    # ---- landing -------------------------------------------------------
    c.group(52, 160, 1128, 594, "landing", "data",
            note="one import_run per load  ·  every row carries import_run_id")

    table(78, 200, 520, "landing.import_run", [
        (1, "id", "bigserial"),
        (0, "source_system", "text", "'SHEET' | 'ODOO'"),
        (0, "spreadsheet_id", "text null"),
        (0, "started_at", "timestamptz"),
        (0, "finished_at", "timestamptz null"),
        (0, "status", "text", "'RUNNING' | 'OK' | 'FAILED'"),
        (0, "row_counts", "jsonb"),
        (0, "reconciled", "boolean null"),
        (0, "truncated_blocks", "jsonb"),
        (0, "note", "text null"),
    ], "data", badge="SHEET + ODOO", code="PRIMARY KEY (id)")

    table(630, 200, 520, "landing.customer", [
        (1, "volt_id", "text"),
        (1, "data_source", "text", "'SHEET' | 'ODOO'"),
        (0, "customer_no", "text"),
        (0, "name_roman", "text"),
        (0, "name_th", "text"),
        (0, "epc", "text"),
        (0, "product", "text"),
        (0, "sales_lead", "text"),
        (0, "phone_masked", "text"),
        (0, "phone_e164", "text"),
        (0, "email_masked", "text"),
        (0, "source_refs", "jsonb"),
        (0, "import_run_id", "bigint", "→ landing.import_run"),
    ], "data", badge="SHEET + ODOO", code="PRIMARY KEY (volt_id, data_source)")

    table(78, 470, 520, "landing.order", [
        (1, "volt_id", "text"),
        (1, "data_source", "text", "'SHEET' | 'ODOO'"),
        (0, "no", "integer"),
        (0, "crm_id", "text"),
        (0, "order_type", "text"),
        (0, "order_status", "text"),
        (0, "loan_status", "text"),
        (0, "submit_date", "date null"),
        (0, "contract_signed_date", "date null"),
        (0, "epc_start_date", "date null"),
        (0, "epc_end_date", "date null"),
        (0, "amount_total", "numeric null"),
        (0, "source_ref", "jsonb"),
        (0, "import_run_id", "bigint", "→ landing.import_run"),
    ], "data", badge="SHEET + ODOO", code="PRIMARY KEY (volt_id, data_source)",
        npad=22)

    table(630, 470, 520, "landing.customer_block", [
        (1, "volt_id", "text"),
        (1, "block", "text"),
        (1, "data_source", "text"),
        (0, "payload", "jsonb"),
        (0, "import_run_id", "bigint", "→ landing.import_run"),
    ], "data", badge="SHEET ONLY", code="PRIMARY KEY (volt_id, block, data_source)")

    c.text(630, 622, "BLOCK — ONE OF SIX", size=10, fill=FAINT, weight=700, spacing=1.1)
    for i, name in enumerate(["leasing", "tracking", "cash",
                              "cash_invoices", "asset", "contact_log"]):
        col, row = i % 3, i // 3
        c.chip(630 + col * 177, 632 + row * 38, 165, 32, name, "data")

    # import_run is the parent of all three
    c.arrow([(598, 290), (628, 290)], tone="data", sw=1.5)
    c.arrow([(338, 404), (338, 468)], tone="data", sw=1.5)
    c.arrow([(598, 350), (614, 350), (614, 530), (628, 530)], tone="data", sw=1.5)

    # ---- app -----------------------------------------------------------
    c.group(1204, 160, 424, 184, "app", "domain", note="written by the app")

    table(1226, 200, 380, "app.session_state", [
        (1, "session_id", "text", "the volt_session cookie"),
        (1, "key", "text"),
        (0, "payload", "jsonb"),
        (0, "updated_at", "timestamptz"),
    ], "domain", badge="APP WRITES", code="PRIMARY KEY (session_id, key)",
        npad=15, tpad=11)

    # ---- the three things this shape buys ------------------------------
    c.note(1204, 364, 424, 126,
           ["• data_source in the primary key is what makes the",
            "\u00a0\u00a0sheet-baseline-plus-Odoo-overlay expressible at all.",
            "\u00a0\u00a0It turns R5's honesty marker from a computed value",
            "\u00a0\u00a0into a STORED FACT — a reviewer can query which",
            "\u00a0\u00a0rung served any row."],
           title="Why the key is composite", tone="data")

    c.note(1204, 506, 424, 126,
           ["• Odoo writes customer and order rows and ZERO",
            "\u00a0\u00a0customer_block rows. sale.order and res.partner",
            "\u00a0\u00a0contain nothing that answers `leasing` or `tracking`.",
            "• This is the same gap already on record as",
            "\u00a0\u00a0'no partner→customer join exists'."],
           title="What Odoo cannot fill", tone="external")

    c.note(1204, 648, 424, 112,
           ["• payload for block='leasing' is byte-identical to",
            "\u00a0\u00a0fixtures_sheet.json customers[i].leasing.",
            "• That is exactly what lets the seam be a single",
            "\u00a0\u00a0loader instead of a rewrite."],
           title="Why the seam is a loader, not a rewrite", tone="domain")

    c.legend(52, c.h - 75, [("landing schema", "data"), ("app schema", "domain"),
                            ("the Odoo gap", "external")])
    c.footer("pictures/GCP design/03-schema.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
