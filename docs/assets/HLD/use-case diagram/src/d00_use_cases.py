"""The use-case overview — who may do what, and where the system boundary is.

A UML use-case diagram: actors outside, the system as one boundary, use cases as
ellipses, associations as lines. The three «include» edges are routed through the
gaps between rows so no long dashed line ever cuts a bubble in half.

Each use case carries the role that guards it and the entry point that serves it,
because the register sheet (01) is where the detail lives and a diagram that hides
the guard invites the wrong person to assume they can act.
"""
from hld_lib import Canvas

COLS = [560, 860, 1160, 1460, 1760]            # x of each column of use cases
ROWS = [270, 430, 590, 750, 910, 1070, 1230]   # y of each row
RX, RY = 138, 44

# (actor, col, row) — the PRIMARY actor of each use case. Shared roles ride in the
# badge/sub; the register sheet owns the full role lists and the refusals.
ASSOC = [
    ("officer", 1, 1), ("officer", 1, 2), ("officer", 1, 3),
    ("officer", 1, 4), ("officer", 1, 5), ("officer", 1, 6),
    ("officer", 3, 1), ("officer", 3, 4), ("officer", 3, 6),
    ("officer", 4, 2), ("officer", 4, 3), ("officer", 5, 1),
    ("supervisor", 2, 1), ("supervisor", 2, 2), ("supervisor", 2, 3),
    ("manager", 2, 4), ("manager", 3, 2), ("manager", 3, 3),
    ("manager", 4, 1), ("manager", 4, 5), ("manager", 4, 6), ("manager", 5, 6),
    ("owner", 2, 5), ("owner", 2, 6), ("owner", 3, 5), ("owner", 5, 5),
    ("ops", 4, 4), ("ops", 5, 2), ("ops", 5, 4),
    ("google", 5, 1), ("odoo", 5, 2), ("peak", 5, 3), ("webhook", 5, 7),
]

# key -> (x, y, name, sub) — y is the top of the head; the association leaves at y+28
ACTORS = {
    "officer":    (170, 330, "Debt collection officer", "OFFICER", 0),
    "supervisor": (170, 490, "Collection supervisor", "SUPERVISOR", 3),
    "manager":    (170, 650, "Collection manager", "MANAGER", 6),
    "owner":      (170, 810, "Owner / admin", "OWNER", 9),
    "ops":        (170, 1130, "Ops / UAT tester", "OPS · own session", 12),
}

SYSTEM = {
    "google":  (2140, 330, "Google Identity", "Sign in with Google"),
    "odoo":    (2140, 590, "Odoo UAT", "crm.lead, read-only"),
    "peak":    (2140, 850, "PEAK UAT", "draft + read state"),
    "webhook": (2140, 1130, "PEAK payment webhook", "advice in, automatic"),
}

# (col, row) -> (lines, tone, sub, code)
USE = {
    (1, 1): (["Work the", "Today queue"], "client", "7 tiers · officer", "GET /v1/today"),
    (1, 2): (["Log a contact", "& a promise"], "client", "includes next action", "POST /v1/contacts"),
    (1, 3): (["Read the calendar", "& deadlines"], "client", "", "GET /v1/calendar"),
    (1, 4): (["Send a", "reminder batch"], "client", "", "POST /v1/today/reminders:send"),
    (1, 5): (["Open the", "customer record"], "client", "", "GET /v1/cases/by-customer/{uid}"),
    (1, 6): (["Search the book", "& the ⌘K palette"], "client", "", "GET /v1/workbook?q="),

    (2, 1): (["Assign a", "customer"], "client", "SUPERVISOR+", "POST /v1/customers/{uid}/assign"),
    (2, 2): (["Answer a review"], "client", "SUPERVISOR+", "POST /v1/reviews/{uid}:answer"),
    (2, 3): (["Decide a power", "restriction"], "client", "SUPERVISOR+ · MANAGER",
             "POST /v1/power-restrictions/{uid}:{act}"),
    (2, 4): (["Read reports", "& aging"], "domain", "MGR · OWNER · SUP", "GET /v1/reports/team"),
    (2, 5): (["Read & verify", "the audit chain"], "refusal", "OWNER · OPS", "GET /v1/audit"),
    (2, 6): (["Publish the", "weekly edition"], "domain", "OWNER", "POST /v1/reports/weekly:publish"),

    (3, 1): (["Clear gates &", "attach evidence"], "domain", "", "POST /v1/pipeline/{uid}/gates/…"),
    (3, 2): (["Release the", "invoice"], "domain", "role-aware", "POST /v1/pipeline/{uid}:release"),
    (3, 3): (["Record a slip", "or credit note"], "domain", "MANAGER+", "POST /v1/slips · /credit-notes"),
    (3, 4): (["Manage PEAK", "documents"], "external", "", "resend · refresh · resubmit"),
    (3, 5): (["Simulate PEAK", "— stub"], "refusal", "OWNER · dev only", "POST /v1/peak-documents/stub"),
    (3, 6): (["Raise a service", "issue"], "domain", "escalation · fee clock", "POST /v1/service-issues"),

    (4, 1): (["Declare NPL /", "advance the ladder"], "refusal", "MANAGER+ · skip OWNER",
             "POST /v1/cases/{uid}:advance"),
    (4, 2): (["Choose a", "recovery path"], "domain", "rate is an assumption (OQ-31)",
             "POST /v1/npl-cases/{uid}/recovery"),
    (4, 3): (["Record a", "recovery"], "domain", "", "POST /v1/recovery-cases/{uid}/recoveries"),
    (4, 4): (["Manage", "repossession lots"], "domain", "OPS · price OWNER",
             "POST /v1/repossession-lots/{uid}:…"),
    (4, 5): (["Restructure &", "approve"], "refusal", "MGR or OWNER approves",
             "POST /v1/restructures/{uid}:approve"),
    (4, 6): (["Decide a", "manager review"], "refusal", "MGR", "POST /v1/manager-review/{uid}:decide"),

    (5, 1): (["Sign in"], "client", "all roles · Google or password",
             "POST /v1/auth/google · /auth/password"),
    (5, 2): (["Pull or upload", "the book"], "data", "OPS · OWNER", "POST /v1/pipelines/crm-lead:run"),
    (5, 3): (["Create a", "PEAK draft"], "external", "«include» · draft only", "peak_documents.py"),
    (5, 4): (["Run & apply", "a PEAK report"], "data", "OPS · MANAGER+", "POST /v1/peak-pipeline/report:run"),
    (5, 5): (["Configure settings", "& dictionaries"], "neutral", "OWNER", "PUT /v1/settings/…"),
    (5, 6): (["Take the", "book out"], "domain", "reason ≥ 8 characters", "POST /v1/workbook:export"),
    (5, 7): (["Receive a", "payment advice"], "external", "automatic · no actor",
             "POST /v1/webhooks/peak/payments"),
}


def _centre(col, row):
    return COLS[col - 1], ROWS[row - 1]


def _corridor(col, offset):
    base = {1: 400, 2: 708, 3: 1008, 4: 1308, 5: 1604}[col]
    return base + offset


def build():
    c = Canvas(2400, 1620, "USE CASES · OVERVIEW",
               "Volt Debt Collection — the actors, the boundary, and what each may do",
               "Primary actors only on the lines; a badge names the roles a use case is shared with. "
               "Guards, refusals and the full role lists are on the register (sheet 01).")
    c.header()

    c.group(380, 180, 1660, 1260, "Volt Debt prototype", "client",
            note="one deployable unit · actors outside, associations cross the boundary")

    # ---- the use cases ----------------------------------------------------------------
    for (col, row), (label, tone, sub, code) in USE.items():
        cx, cy = _centre(col, row)
        c.ellipse(cx, cy, RX, RY, label, tone, sub=sub or None, code=code)

    # ---- the actors -------------------------------------------------------------------
    for key, (ax, ay, name, sub, off) in ACTORS.items():
        c.person(ax, ay, name, sub, "client")
    for key, (ax, ay, name, sub) in SYSTEM.items():
        c.node(ax, ay, 200, 78, name, [sub], "external")

    # ---- «include» edges: routed through the row gaps, drawn after the bubbles --------
    c.arrow([(1298, 430), (1310, 430), (1310, 510), (1604, 510), (1604, 590), (1622, 590)],
            None, "refusal", dashed=True, sw=1.2)
    c.arrow([(1298, 590), (1310, 590), (1310, 670), (1604, 670), (1604, 590), (1622, 590)],
            None, "refusal", dashed=True, sw=1.2)
    c.arrow([(1598, 590), (1622, 590)], None, "refusal", dashed=True, sw=1.2)

    # ---- the associations ---------------------------------------------------------------
    for actor, col, row in ASSOC:
        tx, ty = _centre(col, row)
        if actor in ACTORS:
            ax, ay, _n, _s, off = ACTORS[actor]
            lx = _corridor(col, off)
            c.arrow([(ax + 42, ay + 28), (lx, ay + 28), (lx, ty), (tx - RX, ty)],
                    None, "client", sw=1.3)
        elif actor == "google":
            c.arrow([(2140, 368), (2050, 368), (2050, 270), (1898, 270)], None, "external", sw=1.4)
        elif actor == "odoo":
            c.arrow([(2140, 628), (1990, 628), (1990, 430), (1898, 430)], None, "external", sw=1.4)
        elif actor == "peak":
            c.arrow([(2140, 888), (1930, 888), (1930, 590), (1898, 590)], None, "external", sw=1.4)
        else:
            c.arrow([(2140, 1168), (2020, 1168), (2020, 1230), (1898, 1230)], None, "external", sw=1.4)

    # ---- notes inside the boundary ---------------------------------------------------------
    c.note(400, 1300, 700, 90,
           ["«include» — Release the invoice, Record a slip or credit note and Record a recovery each",
            "include Create a PEAK draft (col 5, row 3): one intent, one local record, written BEFORE",
            "the call, so a transport failure leaves a re-sendable UNSENT document and never a loss."],
           tone="refusal")
    c.note(1124, 1300, 460, 90,
           ["Sign in is «included» by every use case above;",
            "the two read-only system actors (Odoo, PEAK)",
            "use their own credentials and never sign in."],
           tone="client")
    c.note(1608, 1300, 404, 90,
           ["A use case’s badge names the roles it is",
            "shared with. The register (sheet 01) carries",
            "the full role list, the entry point and the guard."],
           tone="neutral")

    c.legend(80, 1510, [("people / client", "client"), ("collection workflow", "domain"),
                        ("PEAK / outside system", "external"), ("governed or open decision", "refusal"),
                        ("data intake", "data"), ("configuration", "neutral")])
    c.text(1120, 1510, "One use case per bubble. A line means “this actor may start it”; "
                       "it does not mean every call succeeds — the guard decides.", size=10.5,
           fill="#6b7280")
    c.footer("pictures/HLD/use-case diagram/00-use-case-overview.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
