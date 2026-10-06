"""Sheet 1 — the staging topology."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1058, "SHEET 1 — TOPOLOGY",
               "The staging estate, thin by decision",
               "Cloud Run's native Cloud SQL connector removes the VPC, the Serverless VPC Access "
               "connector and Cloud NAT in one stroke.")
    c.header()

    # ---- row 1: edge and compute --------------------------------------
    c.group(52, 160, 480, 186, "Edge", "infra", note="volt.co.th only")
    c.node(68, 200, 448, 120, "Identity-Aware Proxy",
           ["Bound to domain:volt.co.th.",
            "The service is deployed --no-allow-unauthenticated,",
            "so nothing is public — not even for the seconds",
            "between deploy and IAP."],
           "infra", code="--no-allow-unauthenticated", badge="IAP")

    c.group(556, 160, 1072, 186, "Compute", "infra", note="one origin, not two")
    c.node(572, 200, 530, 120, "Cloud Run · volt-debt-uat",
           ["ONE service, not two.",
            "FastAPI serves the built frontend from backend/static.",
            "Port 8080."],
           "infra", code="--min-instances 0  --max-instances 4", badge="ONE SERVICE")
    c.note(1122, 200, 490, 120,
           ["• A split web tier must mint an identity token",
            "  per call to a private API service, which",
            "  nginx cannot do natively. One origin removes",
            "  that requirement entirely."],
           title="Why one service and not two", tone="refusal")

    # ---- row 2: jobs and schedule --------------------------------------
    c.group(52, 376, 1576, 176, "Jobs and schedule", "infra",
            note="Cloud Run Jobs · Cloud Scheduler")

    c.node(68, 416, 501, 120, "Cloud Run Job · debt-migrate",
           ["Applies migrations. Runs to completion before a",
            "revision takes traffic.",
            "Cloud Build already executes this job by name, so",
            "creating it resolves a dangling reference, not a new component."],
           "infra", code="infra/cloudbuild.yaml:33")

    c.node(589, 416, 501, 120, "Cloud Run Job · debt-odoo-sync",
           ["The Odoo pull. A Job, not an HTTP call, deliberately:",
            "Scheduler → Cloud Run behind IAP would need an OIDC",
            "token minted for the IAP client id. A Job has no HTTP",
            "and no IAP in the path."],
           "infra", code="no HTTP  ·  no IAP")

    c.node(1110, 416, 501, 120, "Cloud Scheduler",
           ["odoo-reconcile — nightly 02:00 Asia/Bangkok (decision D-15).",
            "Cloud SQL stop/start jobs — 14 hours × 6 days."],
           "infra", code="02:00 Asia/Bangkok  ·  14h × 6d")

    # ---- row 3: supporting, and the database ---------------------------
    c.group(52, 582, 700, 196, "Supporting", "infra", note="names travel, values do not")
    c.node(68, 622, 400, 128, "Secret Manager",
           ["7 secrets: ODOO_URL, ODOO_DB, ODOO_LOGIN,",
            "ODOO_API_KEY, PEAK_UAT_CONNECT_ID,",
            "PEAK_UAT_PASSWORD, PEAK_UAT_USER_TOKEN.",
            "Names match backend/.env.example exactly."],
           "infra", code="backend/.env.example", badge="7")
    c.chip(488, 622, 248, 36, "Artifact Registry", "infra", sub="the API image")
    c.chip(488, 668, 248, 36, "debt-api-sa · debt-jobs-sa", "infra",
           sub="both are IAM database users")
    c.chip(488, 714, 248, 36, "Budget alert", "infra", sub="USD 100 / month")

    c.group(776, 582, 852, 196, "Data", "data", note="reached without a VPC")
    c.node(792, 622, 820, 128, "Cloud SQL · debt-pg-stg",
           ["PostgreSQL 16  ·  db-custom-1-3840  ·  zonal  ·  20 GB SSD.",
            "Public IP disabled. Reached with --add-cloudsql-instances, Cloud Run's native connector.",
            "IAM database authentication: no password exists to leak.",
            "No VPC, no Serverless VPC Access connector and no Cloud NAT in the path."],
           "data", code="infra/terraform/cloud_sql.tf:36  —  the IAM auth flag is already set",
           badge="NO PUBLIC IP")

    # ---- row 4: what the connector removes, and what it costs ----------
    c.group(52, 808, 760, 150, "Not in this estate", "refusal", note="removed in one stroke")
    c.chip(68, 848, 228, 44, "VPC network", "refusal", sub="not created")
    c.chip(318, 848, 228, 44, "Serverless VPC Access", "refusal", sub="connector not created")
    c.chip(568, 848, 228, 44, "Cloud NAT", "refusal", sub="not created")
    c.text(68, 924,
           "Cloud Run's native Cloud SQL connector reaches debt-pg-stg directly, "
           "so none of these three has to exist.",
           size=11, fill="#6b7280")

    c.note(836, 808, 792, 150,
           ["• ~USD 45–90 / month for the whole staging estate.",
            "  Cloud SQL 35–75, depending on how much of the stop/start window is used.",
            "  Cloud Run 5–15 at min-instances 0. Everything else under 5 combined.",
            "",
            "• GCP Architecture v1.0 §13.2 prices the full staging estate at ~219/month always-on,",
            "  and ~180/month with stop/start."],
           title="What it costs", tone="data")

    # ---- the one path worth drawing ------------------------------------
    c.arrow([(520, 260), (568, 260)], tone="infra")
    c.arrow([(837, 320), (837, 366), (1100, 366), (1100, 616)],
            label="--add-cloudsql-instances", tone="data", label_at=0.5)

    c.legend(52, 983, [("infrastructure", "infra"), ("database", "data"),
                       ("removed by decision", "refusal")])
    c.footer("pictures/GCP design/01-topology.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
