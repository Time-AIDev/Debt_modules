"""Sheet 0 — context."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1010, "SHEET 0 — CONTEXT",
               "GCP staging — who touches it, and what it touches",
               "One project, volt-debt-stg, in asia-southeast1. Nothing here exists yet: "
               "no GCP resource has been created.")
    c.header()

    # ---- row 1: people → the system → the sources ----------------------
    c.group(52, 160, 380, 270, "People", "client",
            note="Google sign-in · domain:volt.co.th")
    c.node(68, 200, 348, 110, "Debt officer · Manager",
           ["Reach the app through IAP.",
            "Google sign-in restricted to domain:volt.co.th"],
           "client", badge="VIA IAP")
    c.node(68, 326, 348, 88, "Arina",
           ["Project Owner on volt-debt-stg.",
            "Performs the four manual steps below."],
           "client", code="owner · volt-debt-stg")

    c.arrow([(436, 255), (484, 255)], label="IAP", tone="client")

    c.group(488, 160, 700, 270, "The system", "infra",
            note="one project · volt-debt-stg · asia-southeast1")
    c.node(504, 200, 300, 110, "Cloud Run service",
           ["One service, not two.",
            "FastAPI serves the built frontend from",
            "backend/static."],
           "infra", code="volt-debt-uat")
    c.node(872, 200, 300, 110, "Cloud SQL",
           ["PostgreSQL 16, private.",
            "Reached by Cloud Run's native connector."],
           "infra", code="debt-pg-stg")
    c.arrow([(808, 255), (868, 255)], label="private", tone="infra")
    c.note(504, 326, 668, 88,
           ["• No GCP resource has been created. Not the project, not the service, not",
            "  the instance. This sheet is a design, not an inventory."],
           title="Nothing here exists yet", tone="refusal")

    c.arrow([(1192, 255), (1240, 255)], label="reads", tone="data")

    c.group(1244, 160, 384, 270, "The sources", "data", note="read paths only")
    c.node(1260, 200, 352, 110, "New Order Master",
           ["A Google Sheet, owned by daniel@volt.co.th.",
            "418 customers."],
           "data", code="SYNTHETIC-SPREADSHEET-ID",
           badge="SHEET X")
    c.node(1260, 326, 352, 88, "Odoo UAT",
           ["JSON-RPC. Never written to.",
            "Currently returns just 5 sale.orders."],
           "external", badge="READ-ONLY")

    # ---- row 2: the four manual steps ----------------------------------
    c.group(52, 460, 1576, 150, "The four manual steps", "client",
            note="performed by Arina, by hand")
    steps = [
        ("1 · Sign in", ["In a browser."], "gcloud auth login"),
        ("2 · Confirm project and billing",
         ["The project id, and the billing account."], "volt-debt-stg"),
        ("3 · IAP OAuth consent screen", ["Console-only."],
         "console.cloud.google.com"),
        ("4 · Push 7 secret values",
         ["The command reads backend/.env.", "Nothing is echoed."],
         "backend/.env"),
    ]
    for i, (title, lines, code) in enumerate(steps):
        c.node(68 + i * 390, 500, 374, 92, title, lines, "neutral", code=code)

    # ---- row 3: the defect this design exists to kill -------------------
    c.note(52, 640, 1576, 80,
           ["• backend/app/session.py keeps every tester's state in a process-local dict.",
            "• A Cloud Run revision restart destroys all of it.",
            "• scripts/deploy_gcp.sh warns about this in its own deploy banner."],
           title="The defect this whole design exists to kill", tone="external")

    # ---- row 4: out of scope --------------------------------------------
    c.group(52, 750, 1576, 144, "Out of scope", "refusal",
            note="not in this design")
    outs = [
        "Production — volt-debt-prd",
        "The Data_Model twelve schemas — that is the MVP",
        "The 32 domain modules and the money engine — untouched",
        "No VPC, NAT, Load Balancer, Cloud Armor",
        "No Memorystore, Pub/Sub, Cloud Tasks, KMS, Identity Platform",
        "The PEAK write path is unchanged",
    ]
    for i, label in enumerate(outs):
        col, row = i % 3, i // 3
        c.chip(68 + col * 520, 790 + row * 48, 504, 40, label, "refusal")

    c.legend(52, c.h - 75, [("people", "client"), ("GCP project", "infra"),
                            ("sources", "data"), ("Odoo · read-only", "external"),
                            ("out of scope", "refusal")])
    c.footer("pictures/GCP design/00-context.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
