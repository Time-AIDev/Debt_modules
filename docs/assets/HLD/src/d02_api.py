"""L2 — the HTTP surface."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1080, "LAYER 2 — API",
               "One FastAPI service: 158 endpoints, and what happens before any of them run",
               "The addresses still begin with /v1 while the documents are at v2.x — every v2 change is "
               "additive under v1.0's own rule, and minting /v2 would be a breaking change needing a plan.")
    c.header()

    # ---- request pipeline ----
    P = [("Browser", ["fetch /api/… carrying the role", "and the officer identity"], "client", "api.js"),
         ("CORS", ["localhost:5173 in dev; deployed", "builds are same-origin"], "api", "main.py:71"),
         ("X-Request-Id", ["Generated when absent, ALWAYS", "echoed — and it is `instance`"], "api", "main.py:161"),
         ("volt_session", ["Cookie → ContextVar → the", "tester's own slice of state"], "api", "main.py:175"),
         ("Router", ["Nine routers plus the", "endpoints main.py still holds"], "api", "routers/"),
         ("Domain", ["Every figure is computed", "here, and only here"], "domain", "money/ · journey.py")]
    for i, (t, lines, tone, code) in enumerate(P):
        x = 52 + i * 268
        c.node(x, 180, 236, 100, t, lines, tone, code=code)
        if i:
            c.arrow([(x - 32, 230), (x - 2, 230)], tone="neutral", sw=1.5)

    # ---- routers ----
    c.group(52, 340, 1000, 470, "Where the 158 endpoints live", "api")
    R = [("journey.py", 51, "cases · PTP · restructure · NPL · repossession · board"),
         ("main.py", 31, "contracts · money · orders · overview · the PEAK webhook"),
         ("today.py", 25, "today · workbook · contacts · reviews · exports"),
         ("reports.py", 11, "weekly · officers · bucket-flow · saved targets"),
         ("settings.py", 11, "dictionaries · band sets · the pending config"),
         ("integrations.py", 9, "Odoo discovery / sync · status overrides"),
         ("pipeline.py", 8, "the five gates before an installation"),
         ("payments.py", 7, "PEAK documents · slips · credit notes"),
         ("imports.py", 3, "the officer's upload — staged, never installed"),
         ("migration.py", 2, "the run report and the gap list")]
    for i, (name, n, blurb) in enumerate(R):
        col, row = i // 5, i % 5
        c.node(76 + col * 476, 384 + row * 82, 452, 70, name, [blurb], "api",
               badge="%d" % n)

    # ---- the contract ----
    c.group(1090, 340, 538, 430, "The response contract", "domain")
    c.node(1114, 384, 490, 122, "RFC 9457 problem details",
           ["code — the ONLY field a client is allowed to branch on",
            "instance — the request id, echoed back to the caller",
            "title / detail — Thai, written for the person reading it"],
           "domain", code="backend/app/errors.py")
    c.node(1114, 526, 490, 88, "Liveness & identity",
           ["/healthz · /readyz — the deploy gate and the verify script",
            "/v1/meta/version — what tree is actually serving this"],
           "domain")
    c.node(1114, 634, 490, 88, "SPA catch-all",
           ["GET /{full_path:path} serves the built interface, so a",
            "deep link into a screen never returns a bare 404"],
           "domain", code="main.py")

    # ---- laws ----
    c.note(52, 840, 1576, 120,
           ["• No arithmetic is performed in the API layer or the interface (REQ-COL-027, Data_Model §7.8). A figure missing from a response is fixed in the domain — never computed in a screen.",
            "• Role and officer travel as headers in place of SSO. The cookie identifies a browser, not a person, and the app is required to say so rather than imply an identity it does not have.",
            "• Every mutable thing is per session. Two testers on one deployment never see each other's approvals — and a revision restart clears every session, which the invitation has to state.",
            "• A governed act names who signed it. X-Volt-Officer is not decoration: round 2 pressed MANAGER while the identity said someone else, and the act was signed with a demo name."],
           title="What this layer holds, and refuses to soften", tone="refusal")

    c.legend(52, 1000, [("client", "client"), ("api & routers", "api"), ("domain", "domain"), ("rules", "refusal")])
    c.footer("pictures/HLD/02-api-layer.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
