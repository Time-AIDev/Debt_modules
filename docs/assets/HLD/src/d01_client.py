"""L1 — the browser."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1180, "LAYER 1 — CLIENT",
               "The browser: eleven screens, one fetch client, no arithmetic",
               "React 18 + Vite single page app. Every figure on every screen was computed by the API; "
               "the interface's job is to say what a number means and refuse to invent one.")
    c.header()

    # ---- bootstrap / shell ----
    c.group(52, 160, 380, 410, "Bootstrap & shell", "client")
    c.node(76, 200, 332, 88, "main.jsx",
           ["StrictMode → PrefsProvider → BrowserRouter", "tokens.css first, then app.css"],
           "client", code="frontend/src/main.jsx")
    c.node(76, 306, 332, 104, "App.jsx",
           ["12 route entries; retired 30-Aug paths redirect",
            "Refetches the four rail counts on every route",
            "change AND on every non-GET success"],
           "client", code="railKpi() · pendingPeakCount()")
    c.node(76, 428, 332, 122, "Shell.jsx",
           ["Rail: แดชบอร์ด, then งานของฉัน · อนุมัติ · ระบบ",
            "One KPI bar: cash-in against a saved target",
            "Breadcrumbs, role switcher, officer identity,",
            "view menu (density · rail width · language)"],
           "client", code="components/Shell.jsx")

    # ---- identity / prefs ----
    c.group(52, 600, 380, 300, "Identity, preferences, language", "client")
    c.node(76, 640, 332, 86, "role.jsx",
           ["readRole() / readOfficer() — synchronous and", "storage-guarded, read on every single request"],
           "client", code="X-Volt-Role · X-Volt-Officer")
    c.node(76, 742, 332, 76, "prefs.jsx",
           ["Density, rail width, language — per browser"],
           "client", code="PrefsProvider · PrefControls")
    c.node(76, 834, 332, 56, "i18n-today · journey · admin · ops",
           ["Thai first, English beside it — four files"], "client")

    # ---- screens ----
    c.group(456, 160, 740, 600, "Screens", "domain", note="eleven, in the order of the officer's day")
    S = [("Dashboard · แดชบอร์ด", "/dashboard", "KPI tiles, BarChart, what to do next"),
         ("Today · วันนี้", "/", "Seven tiers, grouped by customer; board view"),
         ("WorkBook · สมุดงาน", "/workbook", "The whole book: filters, columns, governed export"),
         ("CustomerCase · ลูกค้า", "/customers/:uid", "One case: contacts, PTP, next action, timeline"),
         ("ReviewQueue · รอตรวจ", "/reviews", "What a manager has to decide, and why it arrived"),
         ("InvoicePipeline", "/pipeline", "ใบแจ้งหนี้ก่อนติดตั้ง — the five pre-install gates"),
         ("Payments · เงินเข้าและ PEAK", "/payments", "Drafts not yet approved, slips, credit notes"),
         ("Recovery", "/recovery", "NPL และการเรียกคืน — restructure, repossession lots"),
         ("Reports · รายงาน", "/reports", "Weekly in Jo's shape, officers, bucket flow"),
         ("Settings · ตั้งค่า", "/settings", "Dictionaries, band sets, the pending register"),
         ("DataSources · แหล่งข้อมูล", "/data-sources", "Odoo status, migration report, the gap list"),
         ("Retired routes", "/queues /review /npl …", "Redirect, so a bookmark never lands blank")]
    for i, (t, path, blurb) in enumerate(S):
        col, row = i // 6, i % 6
        x = 480 + col * 356
        y = 200 + row * 88
        c.node(x, y, 340, 76, t, [blurb], "client" if i < 11 else "neutral", code=path)

    # ---- components ----
    c.group(1228, 160, 400, 580, "Shared components", "api", note="26 files")
    COMPONENTS = ["Band", "BarChart", "CaseContactDrawer", "Coded", "DataTable", "EntityChip",
                  "Feedback", "FilterBar", "LadderStep", "Money", "MoneyPosition", "MonthGrid",
                  "NavIcon", "NextAction", "Notice", "PeakState", "Popover", "PrefControls",
                  "Problem", "RoleSwitcher", "RowPattern", "Shell", "Spec", "StatusPair",
                  "TierChip", "role"]
    for i, name in enumerate(COMPONENTS):
        col, row = i % 2, i // 2
        c.chip(1252 + col * 190, 200 + row * 40, 178, 32, name, "api")

    c.note(1228, 770, 400, 120,
           ["• Money never renders a bare number: arrears above,",
            "  outstanding beneath, both labelled.",
            "• Every failure renders Problem.jsx from the API's own",
            "  envelope — never a generic 'something went wrong'."],
           title="Two rules the components keep", tone="refusal")

    c.arrow([(826, 760), (826, 930)], "every screen reads through api.js", tone="api", label_dy=-10)

    # ---- data access ----
    c.group(52, 930, 1576, 140, "Data access & the edge", "api")
    c.node(76, 970, 452, 80, "api.js",
           ["get / post / send over BASE = '/api'; roleHeaders() on every call",
            "Throws with .problem attached, so a screen can render the real reason"],
           "api", code="frontend/src/api.js")
    c.node(548, 970, 420, 80, "volt:changed",
           ["Dispatched on window after every non-GET success —",
            "a four-line event bus, no store, no timer"],
           "api", code="CHANGED_EVENT")
    c.node(988, 970, 300, 80, "Development",
           ["vite proxy /api → 127.0.0.1:8000,", "the /api prefix stripped"],
           "infra", code="vite.config.js")
    c.node(1308, 970, 320, 80, "Deployed",
           ["Same origin, one Cloud Run service —", "no CORS, no second IAP session"],
           "infra", code="scripts/deploy_gcp.sh")

    c.legend(52, 1100, [("shell & screens", "client"), ("components / api", "api"),
                        ("boundary", "domain"), ("edge", "infra"), ("rules", "refusal")])
    c.footer("pictures/HLD/01-client-layer.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
