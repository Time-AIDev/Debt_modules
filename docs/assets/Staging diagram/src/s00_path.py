"""Sheet 0 — the path: laptop, free public UAT, then Google Cloud."""
from hld_lib import Canvas, INK, MUTED, HAIR, TONES


def build():
    c = Canvas(1680, 1000, "STAGING — SHEET 0 · THE PATH",
               "Free public UAT first, Google Cloud next — one container, two homes",
               "The image and the DATABASE_URL seam stay the same in both stacks. Only the host, "
               "the database address and the front door change.")
    c.header()

    # ---- the three stages ------------------------------------------------
    c.group(52, 160, 440, 190, "Today · laptop", "client", note="run_prototype.sh")
    c.node(68, 200, 408, 130, "One machine",
           ["uvicorn :8000 serves the API",
            "vite :5173 serves the interface, /api proxied",
            "DATABASE_URL unset → fixtures, state in memory",
            "A restart clears every tester's work",
            "Reachable from this laptop only"],
           "client", code="backend/.venv · frontend/node_modules")

    c.group(572, 160, 520, 190, "Stage 1 · free public UAT", "api", note="$0 a month")
    c.node(588, 200, 488, 130, "Render + Neon",
           ["Render free web service runs the one container",
            "Neon free Postgres keeps tester work across sleeps",
            "Public HTTPS URL — app login ON from the first deploy",
            "Deploys itself on git push from a private GitHub repo",
            "No Odoo, no PEAK: the committed sheet fixture only"],
           "api", code="Singapore region on both", badge="DO THIS FIRST")

    c.group(1172, 160, 456, 190, "Stage 2 · GCP staging", "infra", note="dept-collection-508109")
    c.node(1188, 200, 424, 130, "Cloud Run + Cloud SQL",
           ["The same container, shipped by deploy_gcp.sh",
            "Cloud SQL debt-pg-stg, already provisioned",
            "IAP admits volt.co.th accounts only",
            "Secret Manager · Odoo sync Job · Scheduler",
            "Billed: Cloud SQL runs around the clock"],
           "infra", code="asia-southeast1", badge="SCRIPTED")

    c.arrow([(492, 265), (572, 265)], label="git push", tone="api")
    c.arrow([(1092, 265), (1172, 265)], label="new URL", tone="infra")

    # ---- what changes ----------------------------------------------------
    c.text(52, 398, "WHAT CHANGES BETWEEN THE TWO STACKS", size=11.5, fill=TONES["neutral"][0],
           weight=700, spacing=1.1)
    cols = [(52, 250), (302, 663), (965, 663)]
    top, head_h, row_h = 414, 34, 40
    rows = [
        ("Front door",
         "onrender.com URL, public. The app login is the only gate",
         "IAP (domain:volt.co.th) first, then the same app login"),
        ("Frontend hosting",
         "Built React app inside the container, served by FastAPI, same origin",
         "Unchanged — same container, same origin, same /api prefix"),
        ("Backend hosting",
         "Render free web service · Docker · 512 MB · sleeps after 15 min idle",
         "Cloud Run volt-debt-uat · 1 vCPU / 512 Mi · 0 to 1 instance"),
        ("Build & deploy",
         "Render builds a root Dockerfile (UI + API) on every push",
         "gcloud run deploy --source → Cloud Build → Artifact Registry"),
        ("Database",
         "Neon Postgres 16 · password URL, sslmode=require",
         "Cloud SQL Postgres 16 · IAM auth through the native connector"),
        ("Schema & seed",
         "Laptop runs app.migrate, then loads fixtures_sheet.json, once",
         "Job debt-migrate runs before the service is pointed at the database"),
        ("Secrets",
         "Render environment variables, typed in the dashboard",
         "Secret Manager, readable by debt-api-sa and debt-jobs-sa only"),
        ("Integrations",
         "None. Odoo and PEAK credentials stay off third-party hosts",
         "debt-odoo-sync Job, Scheduler 02:00 Asia/Bangkok, PEAK UAT secrets"),
        ("Cost",
         "$0 inside the Render and Neon free limits",
         "Cloud SQL billed 24/7; Cloud Run close to zero at UAT traffic"),
    ]
    width = cols[-1][0] + cols[-1][1] - cols[0][0]
    c.rect(52, top, width, head_h + row_h * len(rows), rx=9, fill="#ffffff", stroke=HAIR, sw=1.2)
    c.rect(52, top, width, head_h, rx=9, fill=TONES["neutral"][2], stroke="none")
    for (x, _w), label, tone in zip(cols, ["Concern", "Stage 1 · Render + Neon", "Stage 2 · Cloud Run + Cloud SQL"],
                                    ["neutral", "api", "infra"]):
        c.text(x + 16, top + 22, label, size=12, fill=TONES[tone][0], weight=700)
    for i, (concern, one, two) in enumerate(rows):
        y = top + head_h + i * row_h
        c.line(52, y, 52 + width, y, stroke=HAIR, sw=1)
        c.text(cols[0][0] + 16, y + 25, concern, size=12, fill=INK, weight=650)
        c.text(cols[1][0] + 16, y + 25, one, size=12, fill=MUTED)
        c.text(cols[2][0] + 16, y + 25, two, size=12, fill=MUTED)
    for x, _w in cols[1:]:
        c.line(x, top, x, top + head_h + row_h * len(rows), stroke=HAIR, sw=1)

    # ---- what stays --------------------------------------------------------
    c.group(52, 830, 1576, 100, "What stays the same", "domain", note="why the move is small")
    same = ["One container: FastAPI + built UI", "/api on the same origin",
            "AUTH_MODE=on login", "schema.sql through app.migrate", "db.py's DATABASE_URL seam"]
    for i, label in enumerate(same):
        c.chip(76 + i * 308, 868, 290, 38, label, "domain")

    c.footer("pictures/Staging diagram/00-the-path.svg  ·  src/render.py  ·  generated 2026-09-13",
             right="Volt Debt Collection — staging stacks")
    return c
