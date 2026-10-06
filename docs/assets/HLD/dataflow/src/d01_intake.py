"""Level 1 (part 1) — getting the book in, and putting it in front of the team.

Processes 1.0–3.0, stores D1–D3. The rest of level 1 is on sheets 02–03; process
4.0 is opened up on sheet 04.
"""
from hld_lib import Canvas


def build():
    c = Canvas(1860, 1200, "DATAFLOW — LEVEL 1 · PART 1 OF 3",
               "Sign in · land the book · serve the book",
               "Three processes and three stores. Every door here writes the SAME landing "
               "shape, so nobody downstream can tell which door a row came through.")
    c.header()

    # ---- terminators ---------------------------------------------------------------
    c.node(70, 170, 300, 150, "Debt team (browser)",
           ["OFFICER · SUPERVISOR · MANAGER ·", "OWNER · OPS — one session each.",
            "The pull/upload doors are OPS · OWNER."],
           "client", code="X-Volt-Role per call")
    c.node(1500, 170, 300, 150, "Odoo UAT — crm.lead",
           ["JSON-RPC, discovery-first.", "Read-only: no write verb exists",
            "in the client (R14)."],
           "external", code="crm.lead · search_read")

    # ---- processes -----------------------------------------------------------------
    c.process(430, 330, 68, "1.0", ["Sign in &", "session"],
              ["google · password", "allow-list · roles"])
    c.process(900, 460, 88, "2.0", ["Land the book"],
              ["normalise · rules", "verdicts · receipt"])
    c.process(1360, 310, 72, "3.0", ["Serve the book"],
              ["one seam", "fixture or landing"])

    # the three doors 2.0 accepts
    for i, label in enumerate(["pull crm.lead", "upload sheet", "upload PEAK report"]):
        w = 6.35 * len(label) + 24
        c.chip(520 + i * (w + 14), 590, w, 30, label, "neutral")

    # ---- stores --------------------------------------------------------------------
    c.store(1180, 440, 580, 100, "D3",
            ["CUSTOMERS · IDENTITIES · BY_CUSTOMER / BY_CONTRACT — the served book in process,",
             "rebuilt by reload_book() after a PEAK report is applied. Repeated on sheets 02–03."])
    c.store(760, 760, 620, 160, "D1",
            ["landing.import_run — the durable receipt (read / landed / rejected)",
             "landing.customer · landing.order · landing.customer_block · landing.peak_invoice",
             "records.identity_link · records.user_account · notices",
             "Only OK runs are read; status stays RUNNING / OK / FAILED."])
    c.store(120, 760, 560, 160, "D2",
            ["fixtures_sheet.json — SHEET: 198 contract holders from the real export",
             "fixtures.py · journey.py — SYNTHETIC: the scenario book and journey seed",
             "backend/var/odoo_snapshot.json — the last good sync, labelled cached",
             "docs/odoo-comparison/odoo_compare.md — the rules, read as tables"])

    # ---- flows: people -------------------------------------------------------------
    c.arrow([(370, 218), (428, 266)], "sign-in", "client", sw=1.7)
    c.arrow([(384, 380), (336, 312)], "session", "client", sw=1.7,
            label_anchor="end", label_dy=-2)
    c.arrow([(370, 292), (600, 292), (600, 430), (817, 430)],
            "sheet export · PEAK report export", "client", sw=1.6, label_dy=-6)

    # ---- flows: odoo ---------------------------------------------------------------
    c.arrow([(1500, 312), (1500, 400), (966, 400)],
            "crm.lead pages (500 at a time)", "external", sw=1.7, label_dy=-7)

    # ---- flows: into and out of D1 -------------------------------------------------
    c.arrow([(980, 548), (980, 760)], "rows + verdicts · import_run receipt",
            "data", sw=1.8, label_dy=-8)
    c.arrow([(1200, 748), (1140, 748), (1140, 300), (1288, 300)],
            "OK runs only", "data", sw=1.7, label_at=0.75)

    # ---- flows: the fixture fallback ------------------------------------------------
    c.arrow([(660, 760), (660, 200), (1288, 200)],
            "fixture fallback — no database, or no OK run yet", "data", sw=1.7,
            label_at=0.5, dashed=True, label_dy=-8)

    # ---- flows: the served book ------------------------------------------------------
    c.arrow([(1360, 382), (1360, 440)], "the served book", "domain", sw=1.7, label_dy=-6)

    # ---- allow-list read (dashed: a read, not a write) --------------------------------
    c.arrow([(430, 398), (430, 405), (505, 405), (505, 668), (1100, 668), (1100, 760)],
            "allow-list read", "api", sw=1.4, dashed=True, label_at=0.75, label_dy=-6)

    # ---- the refresh timer -----------------------------------------------------------
    c.arrow([(480, 470), (813, 470)], "every 6 h, if stale", "neutral",
            sw=1.3, dashed=True, label_at=0.92, label_dy=-6)
    c.note(120, 420, 360, 110,
           ["On boot, and every six hours when the last OK run is",
            "older, a background thread pulls again. Never in the boot",
            "path itself: a 34k-row pull cannot hold the app down."],
           title="The refresh clock", tone="neutral")

    # ---- the honesty rules ------------------------------------------------------------
    c.note(120, 950, 560, 130,
           ["• The rules are a markdown table a person edits; a renamed column makes the",
            "loader refuse BY NAME rather than silently return an empty mapping.",
            "• An unmapped value passes through and is flagged in the run report — dropping it",
            "quietly would make a value nobody mapped indistinguishable from one nobody has.",
            "• A failed or refused run ends as FAILED with its problem; it never ends silent."],
           title="What intake refuses to fake", tone="refusal")
    c.note(1180, 830, 580, 120,
           ["• Without DATABASE_URL, 2.0 refuses with database_required — and the app still",
            "boots, serving D2 to 3.0, because refusing and leaking are not the same thing.",
            "• D1 is the only place rows are written; a database that is configured but",
            "unreachable makes the app refuse, never quietly fall back to the fixture."],
           title="The three database states", tone="data")

    c.legend(760, 990, [("people / client", "client"), ("process", "domain"),
                        ("data store", "data"), ("outside system", "external"),
                        ("a read, not a write", "api")])
    c.footer("pictures/HLD/dataflow/01-level-1-intake-and-book.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
