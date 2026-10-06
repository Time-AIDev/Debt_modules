"""Level 1 (part 2) — the collection desk: money, the queue, contacts, decisions,
and the PEAK documents that follow from them.

Processes 4.0–8.0, store D3. Intake is on sheet 01; recovery, reports, settings,
audit and the shell are on sheet 03; 4.0 opens up on sheet 04.
"""
from hld_lib import Canvas


def build():
    c = Canvas(1920, 1300, "DATAFLOW — LEVEL 1 · PART 2 OF 3",
               "Compute · queue · contact · decide · write to PEAK",
               "The officer's day and the decisions above it. Process 4.0 is opened up on "
               "sheet 04; every money figure here is computed when it is read, not stored.")
    c.header()

    # ---- terminators -----------------------------------------------------------------
    c.node(60, 240, 260, 170, "Debt team (browser)",
           ["The officer works the queue;", "supervisor and manager decide;",
            "the owner sets policy. The", "role on each call decides what",
            "the act is allowed to do."],
           "client", code="one Record component")
    c.node(1660, 60, 240, 130, "PEAK payment webhook",
           ["Advice in: already allocated", "or not. Unallocated is", "recorded AS unallocated."],
           "external", code="POST /webhooks/peak/payments")
    c.node(1660, 480, 240, 160, "PEAK UAT",
           ["Draft-only client (C3):", "create + read state.",
            "Read-back UNKNOWN until", "INT-05, and the screen says",
            "“check PEAK”."],
           "external", code="EPC / SPV by entity")

    # ---- processes -------------------------------------------------------------------
    c.process(300, 560, 80, "4.0", ["Compute money", "& position"],
              ["DPD · arrears · penalty", "ladder (indicative)", "read time only"])
    c.process(720, 300, 78, "5.0", ["Order", "today's work"],
              ["seven tiers", "locks · allowances"])
    c.process(1100, 300, 78, "6.0", ["Record work", "& promises"],
              ["contacts · PTPs", "next action · board"])
    c.process(1480, 300, 78, "7.0", ["Review", "& decide"],
              ["reviews · power", "restructure · NPL"])
    c.process(1480, 700, 78, "8.0", ["Track PEAK", "documents"],
              ["23 intents", "draft, never approve"])

    # ---- the store of everything a tester does ----------------------------------------
    c.store(1000, 950, 800, 170, "D3",
            ["journey state · cases · contacts · PTPs · board moves · peak_documents.state",
             "Approvals, overrides and the saved criteria live in per-session Stores —",
             "in memory, written through to app.session_state when a database is configured",
             "(a deploy ignores rows written by another code version). Repeated on sheets 01, 03."])

    # ---- flows: the book in, the queue out ---------------------------------------------
    c.arrow([(1040, 950), (1040, 880), (300, 880), (300, 640)],
            "the served book — schedule · transactions · case state", "data",
            sw=1.7, label_at=0.35, label_dy=-8)
    c.arrow([(380, 560), (520, 560), (520, 300), (642, 300)],
            "DPD · arrears · position · ladder", "domain", sw=1.7)
    c.arrow([(642, 270), (320, 270)], "Today queue · counts", "domain", sw=1.7, label_dy=-7)
    c.arrow([(320, 330), (340, 330), (340, 460), (1100, 460), (1100, 378)],
            "contact · result · next action", "client", sw=1.7, label_at=0.55, label_dy=-6)
    c.arrow([(300, 240), (300, 190), (1480, 190), (1480, 222)],
            "answer · approve · reject", "client", sw=1.7, label_dy=-7)
    c.arrow([(1178, 300), (1402, 300)], "broken PTP · review", "domain", sw=1.7, label_dy=-7)

    # ---- flows: what gets written ------------------------------------------------------
    c.arrow([(1160, 350), (1160, 950)], "contacts · PTPs · case state · board", "api",
            sw=1.7, label_dy=-8)
    c.arrow([(1480, 378), (1480, 622)], "release · restructure · write-off intents",
            "api", sw=1.7, label_dy=-8)
    c.arrow([(200, 410), (200, 750), (1420, 750)], "slip · credit note (Manager+)",
            "client", sw=1.6, label_dy=-7)
    c.arrow([(1480, 778), (1480, 950)], "local document record is the record", "api",
            sw=1.7, label_dy=-8)

    # ---- flows: PEAK and the webhook ----------------------------------------------------
    c.arrow([(1558, 700), (1660, 700)], "drafts", "external", sw=1.7, label_dy=0)
    c.arrow([(1660, 740), (1558, 740)], "state", "external", sw=1.7, label_dy=0)
    c.arrow([(1660, 125), (1600, 125), (1600, 660), (1547, 660)],
            "advice → unallocated + ACC", "external", sw=1.7, label_dy=-7)

    # ---- notes --------------------------------------------------------------------------
    c.note(120, 950, 760, 100,
           ["• Every figure on every lens comes back through 4.0 at read time: DPD, arrears, penalty",
            "accrued-unbilled, the payment position and the indicative ladder rung. Nothing above",
            "stores a money figure, so a stale number cannot disagree with the rule that made it."],
           title="No money table, on purpose", tone="domain")
    c.note(120, 1060, 760, 80,
           ["Every non-GET request is appended to the hash-chained audit log by middleware —",
            "12.0 on sheet 03. No endpoint writes it, so no endpoint can forget to."],
           title="The act log is not a feature of any screen", tone="refusal")
    c.note(1000, 1150, 800, 76,
           ["• CF1 (late-fee rate), OD-02 (allocation order) and OD-04 (NPL threshold) are OPEN: the",
            "engine computes with the declared default and badges it, rather than presenting a guess",
            "as a decision. OQ-31 (discount rate) and SVC-37 (month 37) gate recovery and service billing."],
           title="The open decisions are visible here", tone="refusal")

    c.legend(120, 1200, [("people / client", "client"), ("process", "domain"),
                         ("data store", "data"), ("outside system", "external"),
                         ("state write", "api")])
    c.footer("pictures/HLD/dataflow/02-level-1-collections.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
