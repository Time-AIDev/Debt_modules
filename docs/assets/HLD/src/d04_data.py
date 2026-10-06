"""L4 — data, state and what gets written."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1040, "LAYER 4 — DATA & STATE",
               "A fallback chain with a marker on every row, and no database anywhere",
               "There is no persistence tier. What there is instead: four rungs of source data, a marker "
               "saying which rung served each row, and per-session state that a restart clears.")
    c.header()

    # ---- the chain ----
    c.group(52, 160, 1576, 268, "The fallback chain", "data", note="every row says which rung served it")
    CH = [("Odoo UAT", ["JSON-RPC, discovery-first. Synced on", "startup — guarded, so an unreachable", "Odoo never stops the app booting."], "data_source: ODOO", "external"),
          ("odoo_snapshot.json", ["The last good sync, on disk. Used when", "Odoo is configured but unreachable —", "and it says that it is a cached answer."], "backend/var/", "data"),
          ("fixtures_sheet.json", ["198 customers with contracts, from the", "real New Order Master export, built by", "a CLI script — no upload endpoint."], "data_source: SHEET", "data"),
          ("fixtures.py · journey.py", ["The scenario book and the journey seed.", "Invented, and labelled invented, so no", "reviewer mistakes one for the other."], "data_source: SYNTHETIC", "neutral")]
    for i, (t, lines, code, tone) in enumerate(CH):
        x = 80 + i * 388
        c.node(x, 210, 340, 130, t, lines, tone, code=code)
        if i:
            c.arrow([(x - 48, 275), (x - 2, 275)], tone="data", sw=1.6)
    c.text(432, 366, "not configured", size=10.5, fill="#a86412", weight=600)
    c.text(820, 366, "no snapshot", size=10.5, fill="#a86412", weight=600)
    c.text(1208, 366, "not in the sheet", size=10.5, fill="#a86412", weight=600)
    c.text(80, 400, "R5's honesty marker: identity and history are marked separately, so a reviewer can tell what is real from what was invented — that distinction is the point of the chain.",
           size=11, fill="#6b7280")

    # ---- session state ----
    c.group(52, 490, 760, 300, "Session state — in memory, deliberately", "api")
    c.node(76, 534, 712, 76, "volt_session cookie → ContextVar → Store.for_current()",
           ["Approvals, added and removed orders, the saved criteria default: each tester",
            "gets their own slot, created on first touch. It is isolation, not authentication."],
           "api", code="backend/app/session.py")
    c.node(76, 622, 344, 68, "\"shared\"",
           ["The id when no cookie is present —", "curl, health checks, tests"], "neutral")
    c.node(444, 622, 344, 68, "A restart clears everything",
           ["Cloud Run will restart. Testers", "must be told, not discover it."], "refusal")
    c.node(76, 702, 712, 66, "No database",
           ["infra/terraform/cloud_sql.tf exists and stays unapplied until the MVP needs it"],
           "refusal", code="the store is the fixtures and the migrated book")

    # ---- writes ----
    c.group(868, 490, 760, 300, "What gets written, and where it lands", "external")
    c.node(892, 534, 712, 76, "PEAK document record",
           ["The local record IS the record; PEAK's answer only decorates it. A transport or",
            "mapping failure leaves the document UNSENT — re-sendable, and never lost."],
           "external", code="peak_documents.py · integrations/peak.py")
    c.node(892, 622, 344, 68, "Payment webhook",
           ["Recorded unallocated, raising", "an ACC exception. No guess."], "external")
    c.node(1260, 622, 344, 68, "Workbook export",
           ["A governed POST that records", "who took the book out, and why"], "domain")
    c.node(892, 702, 712, 66, "Odoo is never written to",
           ["A manual adjustment is a local override carrying its provenance (R14)"],
           "refusal", code="read_state returns UNKNOWN rather than guessing (INT-05)")

    c.note(52, 820, 1576, 110,
           ["• A number's rung is part of the number. A screen that shows a SHEET figure beside an ODOO figure without saying so is wrong even when both are right.",
            "• The chain degrades downward and says so at each step; it never silently substitutes. \"Not configured\" is an answer the interface is required to render.",
            "• PEAK read-back is an open question (INT-05). Until it is confirmed, read_state answers UNKNOWN and the screen tells the officer to check PEAK — it does not invent a state."],
           title="Three things this layer will not do for convenience", tone="refusal")

    c.legend(52, 960, [("source data", "data"), ("state", "api"), ("outside", "external"),
                       ("governed", "domain"), ("refusals", "refusal")])
    c.footer("pictures/HLD/04-data-and-state.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
