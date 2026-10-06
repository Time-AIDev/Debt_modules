"""Level 0 — the context diagram: the system as one process, and its terminators."""
from hld_lib import Canvas, MUTED


def build():
    c = Canvas(1780, 1060, "DATAFLOW — LEVEL 0 · CONTEXT",
               "Volt Debt Collection — every outside thing that sends or receives data",
               "One process, ten flows, six terminators. The stores inside the boundary "
               "(files, the landing schema, process memory) appear on the level-1 sheets, not here.")
    c.header()

    # ---- the one process ---------------------------------------------------------
    c.group(620, 170, 540, 600, "0 · the system", "domain", note="one deployable unit")
    c.node(644, 214, 492, 158, "Volt Debt prototype",
           ["React 18 SPA — twelve lenses, Thai-first; computes no money",
            "FastAPI /v1 — 158 endpoints, role + officer headers, RFC 9457 refusals",
            "Money engine — Decimal; DPD, arrears, penalty, ladder (indicative only)",
            "Served book — crm.lead landed in Postgres, else the SHEET fixture",
            "Per-tester session — memory, written through app.session_state"],
           "domain", code="backend/app · frontend/src")
    chips = [("no client-side money", "client"), ("Odoo read-only", "external"),
             ("PEAK drafts only", "external")]
    x = 644
    for label, tone in chips:
        w = 6.35 * len(label) + 24
        c.chip(x, 396, w, 30, label, tone)
        x += w + 14
    c.note(644, 456, 492, 130,
           ["The book is ONE seam: book_source.load() returns the same shape",
            "whether it came from the landing schema or the held fixture, so the",
            "32 domain modules and 158 endpoints never learn where it came from.",
            "Every row carries data_source — SHEET · SYNTHETIC · ODOO."],
           title="The seam that keeps the client honest", tone="data")
    c.note(644, 606, 492, 140,
           ["No money is stored anywhere. DPD, arrears, penalty and the ladder",
            "rung are computed at read time from the served schedule and the",
            "transaction rows, so a stored figure can never disagree with the",
            "rule that produced it."],
           title="Why there is no money table to drift", tone="domain")

    # ---- left terminators ----------------------------------------------------------
    c.node(120, 190, 360, 200, "Debt team (browser)",
           ["OFFICER · SUPERVISOR · MANAGER · OWNER · OPS",
            "Role + officer headers on every call; a volt_session",
            "cookie per tester — isolation, not authentication.",
            "UAT rounds run blind on a frozen build, own session."],
           "client", code="X-Volt-Role · X-Volt-Officer · volt_session")
    c.node(120, 440, 360, 140, "Google Identity Services",
           ["The login card renders Google's own button; the",
            "ID token is checked against the 7 allow-listed",
            "addresses. Anyone else gets not_on_allow_list."],
           "client", code="POST /v1/auth/google")

    # ---- right terminators ---------------------------------------------------------
    c.node(1300, 190, 360, 150, "Odoo UAT — crm.lead",
           ["The served book's majority: leads with a real VOLT id.",
            "Read through JSON-RPC, discovery-first, paged 500.",
            "Never written to — a manual override is local (R14)."],
           "external", code="search_count · search_read")
    c.node(1300, 390, 360, 170, "PEAK UAT — two instances",
           ["23 intents; EPC / SPV chosen by entity + company_id.",
            "create draft + read state, and no third verb (C3).",
            "Read-back is INT-05: read_state answers UNKNOWN",
            "until confirmed, and the screen says check PEAK."],
           "external", code="MODE = DRAFT_ONLY")
    c.node(1300, 610, 360, 130, "PEAK payment webhook",
           ["A payment advice arrives already allocated or not;",
            "an unallocated one is recorded as such and raises",
            "an ACC exception. The system never guesses (OD-02)."],
           "external", code="POST /v1/webhooks/peak/payments")

    # ---- the local database, drawn honestly as optional -----------------------------
    c.node(640, 800, 500, 130, "Local PostgreSQL — volt_debt",
           ["landing.* · records.* · app.session_state · audit.entry",
            "Unset: fixtures and memory stand in, and every screen says so.",
            "The three states are RUNNING, REFUSING, LEAKING — never leaking."],
           "data", badge="optional run mode")

    # ---- flows ---------------------------------------------------------------------
    c.arrow([(480, 246), (620, 246)], "requests", "client", sw=1.7)
    c.arrow([(620, 306), (480, 306)], "payloads", "client", sw=1.7)
    c.arrow([(480, 505), (620, 505)], "ID token", "client", sw=1.7)
    c.arrow([(1160, 240), (1300, 240)], "read", "external", label_dy=0)
    c.arrow([(1300, 286), (1160, 286)], "lead rows", "external", label_dy=0)
    c.arrow([(1160, 432), (1300, 432)], "drafts", "external", label_dy=0)
    c.arrow([(1300, 486), (1160, 486)], "state", "external", label_dy=0)
    c.arrow([(1300, 660), (1160, 660)], "advice", "external", label_dy=0)
    c.arrow([(862, 770), (862, 800)], "writes", "data", label_dy=-6, sw=1.7)
    c.arrow([(920, 800), (920, 770)], "the book", "data", label_dy=-6, sw=1.7)

    # ---- refusals ------------------------------------------------------------------
    c.note(120, 800, 460, 150,
           ["• Odoo is never written to; a manual adjustment is a local override that",
            "carries its provenance (R14).",
            "• PEAK is draft-only by decision C3 — approve, post, update and delete",
            "do not exist in the client, and a test refuses to let them appear.",
            "• An allocatable-looking payment is still not allocated silently: it lands",
            "unallocated with an ACC exception while OD-02 stays open.",
            "• In fixture mode there is no database at all: the app runs on SHEET +",
            "SYNTHETIC rows, and the marker on every row is what keeps that honest."],
           title="What the boundary refuses to do", tone="refusal")

    c.legend(120, 982, [("people / client", "client"), ("the system", "domain"),
                        ("stored or served data", "data"), ("outside systems", "external"),
                        ("deliberate refusal", "refusal")])
    c.text(1220, 982, "Read the arrows as data, not as calls: each label names what moves, "
                      "not which protocol carries it.", size=10.5, fill=MUTED)
    c.footer("pictures/HLD/dataflow/00-level-0-context.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
