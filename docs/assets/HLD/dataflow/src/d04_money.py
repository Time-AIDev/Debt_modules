"""Level 2 — process 4.0 opened up: how one money figure is derived, every read."""
from hld_lib import Canvas


def build():
    c = Canvas(1840, 1300, "DATAFLOW — LEVEL 2 · PROCESS 4.0",
               "The money engine — one pass, at read time, from the served rows",
               "Seven sub-processes. No step writes a figure anywhere: change the business date "
               "or the config and every number below re-derives on the next request.")
    c.header()

    # ---- the config band -----------------------------------------------------------------
    c.store(100, 160, 1640, 96, "D4",
            ["band sets + band_set_code · fee states (fee paused, clock paused, or both) · penalty rate default ·",
             "allocation order · ladder_mode · EPC / SPV routing · dictionaries",
             "CF1 (rate), OD-02 (order) and OD-04 (threshold) are OPEN: the engine uses the declared default and badges it."])

    # ---- the book ------------------------------------------------------------------------
    c.store(100, 330, 360, 150, "D3",
            ["the served book, in process:",
             "instalment schedule · PMT plan ·",
             "transactions and receipts ·",
             "case state and fee state."])

    # ---- the chain -----------------------------------------------------------------------
    c.process(600, 340, 72, "4.1", ["Build the", "schedule"], ["instalments", "month grid"])
    c.process(920, 340, 72, "4.2", ["Age it"], ["DPD per contract", "null ≠ 0"])
    c.process(600, 620, 72, "4.3", ["Split the", "money"], ["arrears ≠", "outstanding"])
    c.process(920, 620, 72, "4.4", ["Accrue the", "penalty"], ["pause-aware", "unbilled badge"])
    c.process(600, 880, 72, "4.5", ["Allocate", "a receipt"], ["split by order", "unallocated?"])
    c.process(920, 880, 72, "4.6", ["Position", "the case"], ["amount to ask", "exceptions"])
    c.process(1260, 620, 72, "4.7", ["Place the", "ladder rung"], ["indicative only", "ACTS is human"])

    # ---- what every lens receives ----------------------------------------------------------
    c.node(1440, 330, 340, 290, "Served to every lens — as data",
           ["Today — tier, arrears, oldest DPD, aging band",
            "Record — the six-field money grid",
            "Reports — aging, receipts, DSO, NPL roll",
            "Workbook — 36 served columns",
            "KPI strip — arrears total, attainment",
            "",
            "No client-side arithmetic (REQ-COL-027)."],
           "domain", code="GET /shell/summary · /today · /workbook")

    # ---- flows: the book in -----------------------------------------------------------------
    c.arrow([(460, 380), (500, 380), (500, 340), (528, 340)], "instalments · PMT",
            "data", sw=1.7, label_at=0.99, label_dy=-6)
    c.arrow([(460, 440), (520, 440), (520, 880), (528, 880)], "transactions",
            "data", sw=1.7, label_at=0.99, label_dy=-6)

    # ---- flows: the chain ---------------------------------------------------------------------
    c.arrow([(672, 340), (848, 340)], "month grid", "domain", sw=1.7, label_dy=-7)
    c.arrow([(920, 412), (920, 520), (600, 520), (600, 548)], "DPD · aging bucket",
            "domain", sw=1.7, label_at=0.6, label_dy=-7)
    c.arrow([(672, 620), (848, 620)], "chargeable arrears", "domain", sw=1.7, label_dy=-7)
    c.arrow([(920, 692), (920, 808)], "penalty accrued (unbilled)", "domain", sw=1.7, label_dy=-7)
    c.arrow([(672, 880), (848, 880)], "allocation lines (OD-02 order)", "domain", sw=1.7, label_dy=-7)
    c.arrow([(992, 880), (1260, 880), (1260, 692)], "payment position", "domain",
            sw=1.7, label_at=0.5, label_dy=-7)
    c.arrow([(992, 340), (1180, 340), (1180, 583)], "DPD + kind, not a decision", "api",
            sw=1.5, dashed=True, label_at=0.5, label_dy=-7)

    # ---- flows: config --------------------------------------------------------------------------
    c.arrow([(80, 256), (80, 620), (528, 620)], "band sets", "refusal", sw=1.3,
            dashed=True, label_at=0.75, label_dy=-7)
    c.arrow([(1080, 256), (1080, 620), (992, 620)], "fee states (CF1 OPEN)", "refusal",
            sw=1.3, dashed=True, label_at=0.25, label_dy=-7)
    c.arrow([(1300, 256), (1300, 560)], "ladder_mode · OD-04 (OPEN)", "refusal", sw=1.3,
            dashed=True, label_dy=-7)
    c.arrow([(1332, 600), (1440, 600)], "rung + badge", "domain", sw=1.7, label_anchor="end", label_dy=-4)
    c.arrow([(992, 860), (1400, 860), (1400, 560), (1440, 560)], "position", "domain",
            sw=1.7, label_at=0.65, label_dy=-7)

    # ---- the two refusal notes --------------------------------------------------------------------
    c.note(100, 1000, 760, 160,
           ["• Arrears and outstanding are two numbers and are never interchanged: the big one is overdue now, the",
            "small one is everything still owed. A DPD before collection begins is null — and null is not 0.",
            "• A fee state pauses the fee, the clock, or both; the penalty line says accrued-UNBILLED until a human",
            "sends the PENALTY_INVOICE intent, so a computed figure is never displayed as a bill.",
            "• An indicative ladder rung is always badged INDICATIVE; ladder_mode can suppress even that. Moving a",
            "stage is a human ACT and needs a reason — the engine never moves it."],
           title="What process 4.0 refuses to decide", tone="refusal")
    c.note(920, 1000, 800, 160,
           ["• The allocation order is OD-02, still open. The engine applies the declared",
            "order and badges the result; a receipt it cannot place is recorded",
            "UNALLOCATED and raises an exception rather than guessing.",
            "• An Odoo-only identity carries no contract and no money: it lands and is",
            "counted, but it never enters an engine loop — the loops all assume a",
            "contract, and an identity is the one thing that has none.",
            "• Change the business date and everything above re-derives; there is no",
            "write path into any figure, so nothing here can go stale."],
           title="The three places a guess would hide", tone="refusal")

    c.legend(100, 1220, [("served rows", "data"), ("engine step", "domain"),
                         ("indicative / read-back", "api"), ("config · open decision", "refusal")])
    c.footer("pictures/HLD/dataflow/04-money-engine-detail.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
