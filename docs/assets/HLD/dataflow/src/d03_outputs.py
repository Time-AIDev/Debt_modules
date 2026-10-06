"""Level 1 (part 3) — recovery, reports, settings, the audit chain, the shell."""
from hld_lib import Canvas


def build():
    c = Canvas(1920, 1300, "DATAFLOW — LEVEL 1 · PART 3 OF 3",
               "Recover · report · configure · audit · serve the shell",
               "The processes around the desk. 12.0 is cross-cutting: middleware appends to it, "
               "no endpoint writes it, so no endpoint can forget to.")
    c.header()

    # ---- terminators ------------------------------------------------------------------
    c.node(60, 240, 280, 170, "Debt team (browser)",
           ["Owner and Ops run the data", "doors; the manager reads the",
            "reports; the owner closes a", "write-off. Role decides each."],
           "client", code="X-Volt-Role per call")
    c.node(1660, 300, 220, 150, "PEAK UAT",
           ["Repeated from sheet 02:", "receipts and write-off",
            "documents go out through", "8.0, never from 9.0."],
           "external", code="draft-only (C3)")

    # ---- processes ---------------------------------------------------------------------
    c.process(400, 320, 78, "9.0", ["Recover &", "write off"],
              ["paths · lots", "CLOSING is OWNER"])
    c.process(820, 320, 78, "10.0", ["Report", "& export"],
              ["team · weekly · aging", "CSV / xlsx out"])
    c.process(1240, 320, 78, "11.0", ["Configure"],
              ["settings · band sets", "dictionaries · paths"])
    c.process(900, 700, 78, "12.0", ["Audit", "every act"],
              ["hash chain", "append-only"])
    c.process(1240, 700, 78, "13.0", ["Serve the", "shell"],
              ["KPI · badges", "workload · readyz"])

    # ---- stores ------------------------------------------------------------------------
    c.store(100, 950, 520, 150, "D3",
            ["approvals · overrides · criteria default · recents",
             "Per-session Stores, repeated from sheets 01–02:",
             "in memory, write-through to app.session_state."])
    c.store(760, 950, 700, 150, "D5",
            ["audit.entry — seq · at · actor_claimed · act · subject · hash · prev_hash",
             "Append-only, enforced by a trigger. verify() answers INTACT",
             "(nothing edited) and COMPLETE (nothing missing) as separate claims."])

    # ---- flows: recovery ----------------------------------------------------------------
    c.arrow([(340, 290), (328, 290)], "recovery work", "client", sw=1.6, label_anchor="end", label_dy=-2)
    c.arrow([(328, 350), (340, 350)], "outcomes", "client", sw=1.6, label_dy=0)
    c.note(120, 430, 620, 66,
           ["Every receipt and write-off document this process needs is originated",
            "through 8.0 on sheet 02 — recovery closes a case, it never posts to",
            "the books. PEAK UAT is repeated from sheet 02 for that one reason."],
           tone="external")

    # ---- flows: reports ------------------------------------------------------------------
    c.arrow([(340, 230), (820, 230), (820, 242)], "reports · aging · exports", "client",
            sw=1.7, head_both=True, label_dy=-7)
    c.arrow([(820, 398), (820, 950)], "reads state for reminders & the calendar", "data",
            sw=1.4, dashed=True, label_dy=-8)

    # ---- flows: settings -----------------------------------------------------------------
    c.arrow([(340, 200), (1240, 200), (1240, 242)], "settings · band sets · dictionaries",
            "client", sw=1.7, head_both=True, label_dy=-7)
    c.arrow([(1312, 340), (1400, 340), (1400, 880), (600, 880), (600, 950)],
            "criteria default · overrides", "api", sw=1.5, label_at=0.75, label_dy=-8)

    # ---- flows: the audit bus --------------------------------------------------------------
    c.line(400, 540, 1240, 540, stroke="#8b5cf6", sw=1.3)
    for x in (400, 820, 1240):
        c.arrow([(x, 398 if x != 1240 else 398), (x, 540)], None, "refusal", dashed=True, sw=1.2)
    c.arrow([(900, 540), (900, 622)], "every non-GET act, by middleware", "refusal",
            sw=1.6, label_at=0.0, label_dy=-7, label_anchor="start")
    c.arrow([(900, 778), (900, 950)], "append (seq · hash · prev_hash)", "refusal", sw=1.7, label_dy=-7)
    c.arrow([(960, 950), (960, 778)], "read · verify()", "api", sw=1.3, dashed=True, label_dy=0)
    c.arrow([(860, 770), (240, 770), (240, 410)], "audit lens — INTACT / COMPLETE is a claim, not a badge",
            "client", sw=1.5, label_at=0.25, label_dy=-7)

    # ---- flows: the shell -------------------------------------------------------------------
    c.arrow([(1240, 622), (1240, 560), (340, 560), (340, 410)],
            "KPI strip · badges · workload · env chip", "client", sw=1.7, label_at=0.3, label_dy=-7)
    c.arrow([(1162, 760), (1162, 820), (580, 820), (580, 950)], "workload read", "data",
            sw=1.4, dashed=True, label_dy=-7)

    # ---- notes ------------------------------------------------------------------------------
    c.note(100, 1112, 900, 66,
           ["• 9.0 closes a write-off only for the OWNER; a repossession lot is a visible state",
            "machine PLANNED → … → SOLD whose price only OPS or OWNER may set — and every",
            "document it needs is originated through 8.0, never posted from here."],
           tone="refusal")
    c.note(1020, 1112, 740, 66,
           ["• 10.0 re-formats the payload the screens already read; the xlsx writer",
            "never recomputes. 13.0 answers the KPI strip, badges and caseload from",
            "one read — no cache to go stale."],
           tone="domain")

    c.legend(100, 1220, [("people / client", "client"), ("process", "domain"),
                         ("data store", "data"), ("outside system", "external"),
                         ("audit / refusal", "refusal")])
    c.footer("pictures/HLD/dataflow/03-level-1-books-outputs-and-audit.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
