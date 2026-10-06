"""L3 — the domain."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1230, "LAYER 3 — DOMAIN",
               "The money engine, the officer's day, and the journey the team actually runs",
               "Thirty-two modules — every domain file in backend/app. The rules live here in the open, "
               "including the five that are not decided yet, which the register names rather than guessing.")
    c.header()

    def stack(x, y, w, items, tone):
        for i, (name, blurb) in enumerate(items):
            c.node(x, y + i * 60, w, 56, name, [blurb], tone)

    c.group(52, 160, 520, 600, "Money engine", "domain", note="Decimal, never float")
    stack(76, 200, 472, [
        ("money/schedule.py", "Flat rate: interest on the full loan for the full term"),
        ("money/dpd.py", "Days past due — null before collection begins, and null is not 0"),
        ("money/band_sets.py", "Bucket + band_set_code; the pair identifies a band, the code alone does not"),
        ("money/penalty.py", "Accrual net of frozen and reset days; nothing inside the 14-day grace"),
        ("money/allocation.py", "Oldest due instalment first — the order within one is OD-02, still open"),
        ("money/fee_states.py", "A TABLE, not logic: every screen and job reads pause behaviour here"),
        ("money/arrears.py", "The arrears block, in the fixed order the tests enforce"),
        ("money/models.py", "total and outstanding are generated — neither can drift"),
    ], "domain")

    c.group(600, 160, 520, 600, "The officer's day", "client")
    stack(624, 200, 472, [
        ("collections/contact.py", "The daily slot: one logged contact per customer per day"),
        ("cases.py", "One case per customer: two statuses, one mandatory next action"),
        ("today.py", "Seven tiers in sequence; every item names the tier that won"),
        ("ladder.py", "The deck's rungs — contractual acts moved by humans, not automation"),
        ("criteria.py", "Saved review criteria; refuses an implicit whole-book default"),
        ("officers.py", "Who signs a governed act, and under which role"),
        ("book.py", "The migrated book: 198 customers with contracts"),
        ("orders.py", "Order intake and the loan book"),
        ("overview.py", "The executive overview: progress against targets, and what to do next"),
    ], "client")

    c.group(1148, 160, 480, 600, "The journey", "data")
    stack(1172, 200, 432, [
        ("journey.py", "AR pipeline, PTP, restructure, review, NPL, service, inter-company"),
        ("invoice_pipeline.py", "The five gates that stand before an installation"),
        ("peak_documents.py", "23 intents; one record per document Debt originates"),
        ("entities.py", "EPC / SPV routed on company_id — one field, not a set of conditions"),
        ("migration.py", "The run report, the reconciliation, and the gap list"),
        ("imports.py", "The officer's upload: parsed and staged, never installed"),
        ("dictionaries.py", "Six governed lists; a value is deactivated, never deleted"),
        ("reports.py · collection_kpi.py", "The weekly report in Jo's shape, and the two indicators"),
        ("uat_tasks.py", "The round's task script — tasks, not a tour, so the findings are real"),
    ], "data")

    c.group(52, 790, 1576, 180, "Governance", "infra", note="the parts that keep the rest honest")
    G = [("config.py", ["The register of what is NOT decided. Every", "pending value carries the decision that", "gates it and the owner who must close it."], "CF1 · OD-02 · OD-04 · OQ-31 · SVC-37"),
         ("clock.py", ["One clock. Business date plus the machine's", "own time-of-day once wrote stamps nobody", "could defend; now there is one source."], "round-3 J3-19"),
         ("errors.py", ["RFC 9457 problem details. `code` is the only", "field a client branches on, so it is the one", "field that may never be improvised."], "the envelope §2.4 fixes"),
         ("workbook_exports.py", ["Who took the book out, and why. The", "governed POST — and the ungrouped GET", "that used to answer 200 to anyone, closed."], "rulings 72 · 74"),
         ("feedback.py", ["Deliberately NOT per-session: feedback is", "the output of a UAT round, not a tester's", "private state to be isolated away."], "UAT rounds")]
    for i, (name, lines, code) in enumerate(G):
        c.node(52 + i * 320, 840, 296, 110, name, lines, "infra", code=code)

    c.note(52, 1000, 1576, 120,
           ["• Money is Decimal end to end (ADR-006 §Decision 2). A float anywhere in this layer is a defect, not a rounding difference.",
            "• The ladder and the aging band sets are different instruments. The system computes an INDICATIVE rung only, and ladder_mode can suppress even that.",
            "• A figure nobody has agreed to bill is badged indicative wherever it appears — the badge is part of the number, not decoration around it.",
            "• Nothing anywhere derives pause behaviour. fee_states.py is a table; a second implementation of it would be the bug, however correct it looked."],
           title="Laws that outrank convenience", tone="refusal")

    c.legend(52, 1150, [("money", "domain"), ("the day", "client"), ("journey", "data"),
                        ("governance", "infra"), ("laws", "refusal")])
    c.footer("pictures/HLD/03-domain-layer.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
