"""Sheet 2 — the GCP staging stack, as scripts/deploy_gcp.sh builds it."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1020, "STAGING — SHEET 2 · GCP STAGING STACK",
               "Cloud Run + Cloud SQL — the same container behind IAP, with the integrations switched on",
               "Read from scripts/provision_stg.sh, push_secrets.sh and deploy_gcp.sh. Detailed design: "
               "pictures/GCP design/ (sheets 00–06).")
    c.header()

    # ---- people --------------------------------------------------------------
    c.group(52, 150, 300, 390, "People", "client")
    c.node(68, 195, 268, 140, "UAT testers",
           ["volt.co.th Google account", "passes IAP first, then the",
            "app login (test accounts or", "the Google allow-list)"],
           "client")
    c.node(68, 385, 268, 120, "Developer laptop",
           ["provision_stg.sh (done)", "push_secrets.sh --apply", "deploy_gcp.sh"],
           "client", code="gcloud, no Docker needed")

    # ---- Google Cloud ----------------------------------------------------------
    c.group(392, 150, 1236, 570, "Google Cloud · dept-collection-508109", "infra", note="asia-southeast1")

    c.node(420, 195, 260, 140, "Identity-Aware Proxy",
           ["domain:volt.co.th →", "iap.httpsResourceAccessor", "Service deployed", "--no-allow-unauthenticated"],
           "infra", badge="IAP")
    c.node(720, 195, 400, 140, "Cloud Run · volt-debt-uat",
           ["The SAME container as Stage 1: FastAPI + built UI",
            "1 vCPU · 512 Mi · min 0 / max 1 instance",
            "Runs as debt-api-sa · AUTH_MODE=on",
            "Secrets mounted as environment variables"],
           "infra", code="gcloud run deploy --source", badge="SERVICE")
    c.node(1160, 195, 440, 140, "Cloud SQL · debt-pg-stg",
           ["PostgreSQL 16 · Enterprise · db-custom-1-3840",
            "IAM database auth, no passwords",
            "Public IP with ZERO authorized networks —",
            "reached only by the native connector (D9)"],
           "data", badge="PAID 24/7")

    c.node(420, 385, 260, 120, "Cloud Build",
           ["Builds the image from", "the uploaded source"], "infra")
    c.node(720, 385, 400, 120, "Artifact Registry",
           ["Image per deploy", "One image serves the service and both Jobs"], "infra")
    c.node(1160, 385, 440, 120, "Secret Manager",
           ["AUTH_SESSION_SECRET · AUTH_TEST_ACCOUNTS · AUTH_ALLOWLIST",
            "ODOO_URL · ODOO_DB · ODOO_LOGIN · ODOO_API_KEY",
            "PEAK_UAT_CONNECT_ID · _PASSWORD · _USER_TOKEN"],
           "infra", code="GOOGLE_CLIENT_ID once the OAuth client exists")

    c.node(420, 580, 260, 110, "Cloud Scheduler",
           ["odoo-reconcile", "0 2 * * * Asia/Bangkok"], "infra")
    c.group(700, 555, 896, 150, "Cloud Run Jobs · run as debt-jobs-sa", "domain")
    c.node(720, 590, 420, 100, "debt-odoo-sync",
           ["python -m app.jobs.odoo_sync", "Odoo → landing schema, nightly"], "domain")
    c.node(1160, 590, 420, 100, "debt-migrate",
           ["python -m app.migrate", "Runs BEFORE the service gets DATABASE_URL"], "domain")

    # request path
    c.arrow([(336, 265), (418, 265)], label="HTTPS", tone="client")
    c.arrow([(680, 265), (718, 265)], tone="infra")
    c.arrow([(1120, 265), (1158, 265)], tone="data")
    # build path
    c.arrow([(336, 445), (418, 445)], label="--source", tone="client")
    c.arrow([(680, 445), (718, 445)], tone="infra")
    c.arrow([(920, 385), (920, 337)], label="image", tone="infra", label_anchor="start", label_dy=4)
    # secrets feed the service
    c.arrow([(1160, 470), (1140, 470), (1140, 310), (1122, 310)], tone="infra", dashed=True)
    # schedule and jobs
    c.arrow([(680, 635), (718, 635)], tone="infra")
    c.arrow([(1580, 640), (1614, 640), (1614, 300), (1602, 300)], tone="domain", dashed=True)

    # ---- outside GCP -------------------------------------------------------
    c.group(392, 760, 740, 130, "Outside Google Cloud", "external")
    c.chip(420, 812, 320, 46, "PEAK UAT", "external", sub="read by the service with PEAK_UAT_* secrets")
    c.chip(780, 812, 320, 46, "Odoo UAT", "external", sub="XML-RPC · the UAT order book")
    c.arrow([(930, 690), (930, 810)], tone="external")

    c.note(1172, 760, 456, 130,
           ["• gcloud auth login — tokens expired, checked 2026-09-13",
            "• IAP OAuth consent screen (console only)",
            "• OAuth Web client ID, for Google sign-in",
            "• Budget alert on the billing account"],
           title="Still manual — only Arina can do these", tone="refusal")

    c.note(52, 570, 300, 320,
           ["1  Run the four manual steps (right)",
            "2  push_secrets.sh --apply",
            "3  deploy_gcp.sh: verify, build,",
            "   debt-migrate, attach Cloud SQL",
            "4  Seed landing from the fixture,",
            "   or let debt-odoo-sync fill it",
            "5  Smoke-test every role",
            "6  Send the new URL",
            "7  Suspend Render; keep Neon until",
            "   sign-off, then delete it",
            "",
            "Tester work does NOT carry over:",
            "it is keyed to a browser cookie",
            "on the onrender.com domain."],
           title="Moving over from Stage 1", tone="api")

    c.legend(52, 950, [("people", "client"), ("GCP managed", "infra"), ("database", "data"),
                       ("jobs", "domain"), ("external", "external"), ("manual", "refusal")])
    c.footer("pictures/Staging diagram/02-gcp-staging-stack.svg  ·  src/render.py  ·  generated 2026-09-13",
             right="Volt Debt Collection — staging stacks")
    return c
