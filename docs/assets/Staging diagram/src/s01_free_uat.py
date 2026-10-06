"""Sheet 1 — the free public UAT stack: Render web service + Neon Postgres."""
from hld_lib import Canvas, MONO, MUTED


def build():
    c = Canvas(1680, 1020, "STAGING — SHEET 1 · FREE PUBLIC UAT STACK",
               "Render hosts the container, Neon keeps the data — both free, both in Singapore",
               "Frontend and backend ship as ONE container on ONE origin, as deploy_gcp.sh already does. "
               "No CORS, and the login cookie stays first-party.")
    c.header()

    # ---- people and source -----------------------------------------------
    c.group(52, 150, 300, 450, "People & source", "client")
    c.node(68, 195, 268, 96, "UAT testers",
           ["Any browser, Thai-first interface", "Sign in: test account, or an", "allow-listed Google login"],
           "client")
    c.node(68, 335, 268, 96, "Developer laptop",
           ["Pushes the branch", "Runs migrate + seed once,", "pointed at Neon"],
           "client")
    c.node(68, 475, 268, 96, "GitHub · private repo",
           ["Render deploys from git", "Must stay PRIVATE: the fixture", "holds real customer names"],
           "client", badge="PRIVATE")
    c.arrow([(202, 431), (202, 473)], tone="client")

    # ---- Render ------------------------------------------------------------
    c.group(392, 150, 720, 450, "Render · free web service", "api", note="region: Singapore")
    c.node(420, 195, 300, 96, "HTTPS edge",
           ["volt-debt-uat.onrender.com", "TLS by Render · health check /healthz", "Spins down after 15 min idle"],
           "api", badge="FREE")
    c.node(420, 475, 300, 96, "Render build",
           ["Root Dockerfile, two stages:", "node 22 → npm run build (the UI)",
            "python 3.12 → app + static + importer"],
           "api", code="auto-deploy on push")

    c.node(760, 195, 324, 376, "Container · volt-debt-uat",
           ["uvicorn app.main:app on $PORT", "512 MB RAM · 0.1 CPU"], "api")
    inner = [("Login gate", "AUTH_MODE=on · test accounts + Google"),
             ("/api/v1/*  →  FastAPI routes", "prefix stripped in main.py"),
             ("/  →  built React app", "backend/static, same origin"),
             ("Session state  →  Postgres", "tester work survives sleep + redeploy"),
             ("Environment variables", "typed in the Render dashboard")]
    for i, (label, sub) in enumerate(inner):
        c.chip(780, 262 + i * 60, 284, 48, label, "api", sub=sub)

    c.arrow([(336, 243), (418, 243)], label="HTTPS", tone="client")
    c.arrow([(720, 243), (758, 243)], tone="api")
    c.arrow([(336, 523), (418, 523)], label="git push", tone="client")
    c.arrow([(720, 523), (758, 523)], tone="api")

    # ---- Neon --------------------------------------------------------------
    c.group(1152, 150, 476, 450, "Neon · free Postgres", "data", note="aws-ap-southeast-1")
    c.node(1176, 195, 428, 110, "Serverless Postgres 16",
           ["Pick 16 to match Cloud SQL debt-pg-stg",
            "0.5 GB storage · 100 compute-hours a month",
            "Scales to zero after 5 min idle"],
           "data", badge="FREE")
    tables = [("landing.*", "import_run · customer · order · customer_block"),
              ("app.session_state", "one row per browser session and key"),
              ("audit.entry", "append-only, enforced by a trigger")]
    for i, (label, sub) in enumerate(tables):
        c.chip(1176, 325 + i * 58, 428, 46, label, "data", sub=sub)
    c.text(1176, 522, "DATABASE_URL shape", size=11, fill=MUTED, weight=600)
    c.text(1176, 542, "postgresql+psycopg://USER:PASS@ep-….ap-southeast-1", size=11, fill=MUTED, font=MONO)
    c.text(1176, 558, "  .aws.neon.tech/neondb?sslmode=require", size=11, fill=MUTED, font=MONO)
    c.text(1176, 580, "+psycopg is required: psycopg2 is not installed", size=10.5, fill="#a86412")

    c.arrow([(1084, 243), (1174, 243)], label="SQL · TLS", tone="data")

    # ---- one-time setup ------------------------------------------------------
    c.group(52, 630, 1576, 140, "One-time setup, in order", "domain", note="about an hour")
    steps = [("1  Neon project", "Singapore · Postgres 16 · copy URL"),
             ("2  python -m app.migrate", "DATABASE_URL=<Neon> · idempotent"),
             ("3  Seed the book", "fixtures_sheet.json → sheet_loader"),
             ("4  Render web service", "repo · Docker · Free · Singapore · env"),
             ("5  Smoke test, then share", "/healthz · log in as each role")]
    for i, (label, sub) in enumerate(steps):
        c.chip(76 + i * 308, 672, 290, 52, label, "domain", sub=sub)
        if i:
            c.arrow([(76 + i * 308 - 16, 698), (76 + i * 308 - 2, 698)], tone="domain", sw=1.4)
    c.arrow([(530, 670), (530, 636), (1390, 636), (1390, 602)], tone="domain", dashed=True)
    c.text(76, 752, "Env vars on Render: ENV=uat · DATABASE_URL · AUTH_MODE=on · AUTH_ALLOW_TEST_ACCOUNTS=true · "
           "AUTH_SESSION_SECRET (new, not the laptop's) · AUTH_TEST_ACCOUNTS · AUTH_ALLOWLIST · GOOGLE_CLIENT_ID (later)",
           size=11, fill=MUTED, font=MONO)

    # ---- refusals and limits ---------------------------------------------
    c.group(52, 800, 760, 120, "Deliberately not wired here", "refusal", note="arrive with Stage 2")
    for i, label in enumerate(["Odoo UAT sync", "PEAK UAT", "Jobs + Scheduler", "IAP"]):
        c.chip(76 + i * 182, 840, 166, 34, label, "refusal")
    c.text(76, 900, "ERP credentials never leave Volt-owned infrastructure.", size=11, fill=MUTED)

    c.note(852, 800, 776, 120,
           ["• The first request after 15 idle minutes waits about a minute while Render wakes up",
            "• 750 free instance-hours a month per workspace: one always-on service fits",
            "• 512 MB: a 25 MB xlsx upload can run out of memory — keep test files small",
            "• Free tiers carry no SLA. Fine for UAT, never for live collection work"],
           title="Limits testers will feel", tone="external")

    c.legend(52, 950, [("people & source", "client"), ("Render", "api"), ("Neon", "data"),
                       ("setup", "domain"), ("not wired", "refusal"), ("limits", "external")])
    c.footer("pictures/Staging diagram/01-free-uat-stack.svg  ·  src/render.py  ·  generated 2026-09-13",
             right="Volt Debt Collection — staging stacks")
    return c
