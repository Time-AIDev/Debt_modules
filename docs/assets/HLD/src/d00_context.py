"""L0 — system context."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1090, "LAYER 0 — CONTEXT",
               "Volt Debt Collection — who touches the system, and what it touches",
               "One deployable unit, five things outside it, and a short list of what it refuses to do. "
               "Read from the running tree on 2026-09-09, not from the deck.")
    c.header()

    # ---------------- people ----------------
    c.group(52, 160, 330, 460, "People", "client", note="role on every request")
    A = [("Debt officer", ["The seven-tier วันนี้ list, contacts,", "PTPs, the mandatory next action"], "X-Volt-Role: OFFICER"),
         ("Collection manager", ["Review queue, weekly targets,", "governed overrides"], "X-Volt-Role: MANAGER"),
         ("Owner / admin", ["Settings, dictionaries, band sets,", "workbook exports"], "X-Volt-Role: OWNER"),
         ("UAT tester", ["Blind rounds against a frozen", "production build"], "own volt_session cookie")]
    y = 210
    for t, lines, code in A:
        c.node(76, y, 282, 84, t, lines, "client", code=code)
        y += 96

    # ---------------- the system ----------------
    c.group(430, 160, 760, 560, "Volt Debt prototype", "domain", note="one Cloud Run service")
    c.node(458, 210, 704, 92, "Browser SPA",
           ["React 18 + Vite · react-router · 12 routes · Thai-first, th / en",
            "Renders figures only — no arithmetic in the interface (REQ-COL-027)"],
           "client", code="frontend/src/App.jsx", badge="L1")
    c.arrow([(810, 302), (810, 344)], tone="neutral")
    c.node(458, 350, 704, 92, "FastAPI service",
           ["/v1 HTTP surface · 158 endpoints · RFC 9457 problem envelope",
            "Session cookie per tester · role + officer headers in place of SSO"],
           "api", code="backend/app/main.py + routers/", badge="L2")
    c.arrow([(810, 442), (810, 484)], tone="neutral")
    c.node(458, 490, 704, 92, "Money engine · journey domain · in-memory state",
           ["Decimal money · seven Today tiers · 23 PEAK intents · EPC / SPV routing",
            "State lives in process memory keyed by session — a restart clears it"],
           "domain", code="backend/app/{money,collections,journey}", badge="L3 · L4")
    c.note(458, 610, 704, 74,
           ["No database. The scenario fixtures and the migrated book are the store; every row",
            "carries data_source (SHEET · SYNTHETIC · ODOO) so a reviewer can tell real from invented."],
           tone="data")

    # ---------------- outside ----------------
    c.group(1268, 160, 360, 664, "Outside", "external", note="creds in backend/.env")
    c.node(1292, 200, 312, 84, "Odoo UAT", ["Orders, contracts, partners.", "READ only — never written back (R14)."],
           "external", code="JSON-RPC · discovery-first")
    c.node(1292, 296, 312, 84, "PEAK UAT", ["create_draft · read_state, and no", "third verb — decision C3."],
           "external", code="MODE = DRAFT_ONLY")
    c.node(1292, 420, 312, 84, "AR / accounting", ["Approves the draft into the books.", "Debt never posts; a person does."],
           "client", code="inside PEAK, not in this app")
    c.node(1292, 516, 312, 84, "PEAK payment webhook", ["Recorded unallocated, raising an", "ACC exception. Never guesses."],
           "external", code="POST /v1/webhooks/peak/payments")
    c.node(1292, 612, 312, 84, "New Order Master", ["198 customers with contracts,", "imported by a CLI script."],
           "data", code="Drive export → fixtures_sheet.json")
    c.node(1292, 708, 312, 84, "Google Cloud", ["Cloud Build → Artifact Registry", "→ Cloud Run, behind IAP."],
           "infra", code="asia-southeast1")
    c.arrow([(1448, 420), (1448, 386)], tone="client", dashed=True, sw=1.4)
    c.text(1462, 406, "approves", size=10.5, fill="#2f5fbe", weight=600)

    # ---------------- wires ----------------
    for ay in (252, 348, 444, 540):
        c.arrow([(358, ay), (400, ay), (400, 256), (458, 256)], tone="client", sw=1.2)
    c.text(404, 244, "HTTPS", size=10.5, fill="#2f5fbe", weight=600)

    c.arrow([(1162, 380), (1200, 380), (1200, 242), (1292, 242)], "sync · read", tone="external", label_at=0.9)
    c.arrow([(1162, 412), (1218, 412), (1218, 338), (1292, 338)], "drafts", tone="external", label_at=0.9)
    c.arrow([(1292, 558), (1236, 558), (1236, 430), (1162, 430)], "paid", tone="external", label_at=0.9)
    c.arrow([(1292, 654), (1254, 654), (1254, 566), (1162, 566)], "the book", tone="data", label_at=0.9)
    c.arrow([(810, 720), (810, 750), (1292, 750)], "build & deploy", tone="infra", label_at=0.9, label_dy=-8)

    # ---------------- refusals ----------------
    c.legend(52, 862, [("people / client", "client"), ("api", "api"), ("domain", "domain"),
                       ("data", "data"), ("external", "external"), ("infra", "infra")])
    c.note(52, 890, 1576, 120,
           ["• No database, no SSO, no file upload anywhere in the backend — the sheet import is a CLI script, not an endpoint.",
            "• PEAK is draft-only: the test suite reflects on the client and fails if a public verb named approve / post / update / delete appears (PKD-001).",
            "• Odoo is never written to. A manual adjustment is a local override carrying its provenance, never a write into a shared UAT system.",
            "• Five money decisions are open and the config register names them: CF1 late-fee rate · OD-02 allocation order · OD-04 NPL threshold · OQ-31 discount · SVC-37 month-37."],
           title="What this system deliberately refuses to do", tone="refusal")
    c.footer("pictures/HLD/00-context.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
