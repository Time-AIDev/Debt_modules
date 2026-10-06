"""One page — the whole GCP staging design on a single canvas.

The six detail sheets each answer one question well. This one exists for the
opposite job: to be shown once, whole, without paging. Everything here is a
compression of a sheet that says it at greater length.
"""
from hld_lib import Canvas


def build():
    c = Canvas(2400, 1660, "ONE PAGE — THE WHOLE GCP STAGING DESIGN",
               "Volt Debt on volt-debt-stg — Cloud SQL, a sheet-shaped landing schema, and the Odoo sync rehosted",
               "Approved 2026-09-10. Nothing here has been built: no GCP resource exists, gcloud holds no "
               "credentialed account, terraform and docker are not installed.")
    c.header()

    # ---------------- band 1 — the estate ----------------
    c.group(52, 160, 2296, 300, "The estate — one project, volt-debt-stg, asia-southeast1", "infra",
            note="thin by decision  ·  ~USD 45–90/mo against v1.0's 219")
    estate = [
        ("Identity-Aware Proxy", ["domain:volt.co.th", "--no-allow-unauthenticated"],
         "never public, not for a second"),
        ("Cloud Run volt-debt-uat", ["ONE service: API + built frontend", "port 8080 · min 0 · max 4"],
         "backend/static"),
        ("Cloud SQL debt-pg-stg", ["PostgreSQL 16 · db-custom-1-3840", "public IP OFF · IAM auth"],
         "no password exists to leak"),
        ("The native connector", ["Removes the VPC, the serverless", "connector and Cloud NAT"],
         "the load-bearing choice"),
        ("Secret Manager", ["7 secrets: 4 ODOO_*, 3 PEAK_UAT_*", "names travel, values do not"],
         "backend/.env.example"),
        ("Job debt-migrate", ["Runs to completion before a", "revision takes traffic"],
         "cloudbuild.yaml:33 names it"),
        ("Job debt-odoo-sync", ["A Job, not an HTTP call — no", "OIDC dance against IAP"],
         "Scheduler 02:00 Asia/Bangkok"),
        ("Registry · budget · SAs", ["The API image · USD 100/mo alert", "debt-api-sa · debt-jobs-sa"],
         "both are IAM database users"),
    ]
    for i, (t, lines, code) in enumerate(estate):
        x = 76 + i * 283
        c.node(x, 205, 263, 118, t, lines, "infra", code=code)
        if i in (1, 2):
            c.arrow([(x - 18, 264), (x - 3, 264)], tone="infra", sw=1.5)

    c.note(76, 340, 2248, 100,
           ["• Cloud Run's native Cloud SQL connector is what makes this thin: it needs no VPC, no Serverless VPC Access connector and no Cloud NAT,",
            "  which deletes three of GCP Architecture v1.0 §4's components at once. IAM database authentication then removes the password as well.",
            "• Both background verbs are Cloud Run Jobs rather than HTTP endpoints, because Scheduler → Cloud Run behind IAP would have to mint an OIDC token for the IAP client id."],
           title="Why the estate is this small", tone="infra")

    # ---------------- band 2 — data path + schema ----------------
    c.group(52, 490, 1420, 340, "The data path — two sources, one landing schema, one seam", "data")
    path = [
        ("Sources", ["New Order Master — 418 customers", "Odoo UAT — 5 sale.orders"], "sheet X · JSON-RPC"),
        ("Ingest", ["import_master_sheet.py --to-postgres", "odoo.py sync(), run by the Job"], "one import_run each"),
        ("landing", ["customer · order · customer_block", "import_run"], "the schema, right →"),
        ("The seam", ["book_source.load() returns the dict", "book.build() already consumes"], "two modules, nothing else"),
        ("Domain", ["book.build() → 32 modules", "158 endpoints → 11 screens"], "untouched"),
    ]
    for i, (t, lines, code) in enumerate(path):
        x = 76 + i * 278
        c.node(x, 535, 260, 120, t, lines, "data" if i < 3 else "domain", code=code)
        if i:
            c.arrow([(x - 16, 595), (x - 3, 595)], tone="data", sw=1.5)

    for i, label in enumerate(["1 · rows from the current ODOO import_run",
                               "2 · else the last previous ODOO run — the SNAPSHOT rung",
                               "3 · else the SHEET rows"]):
        c.chip(76 + i * 466, 675, 440, 40, label, "data")

    c.note(76, 730, 1372, 84,
           ["• Odoo writes customer and order rows and ZERO customer_block rows — sale.order and res.partner hold nothing",
            "  that answers `leasing` or `tracking`. The schema states that boundary instead of hiding it behind NULLs.",
            "• One import run is one transaction. A failed run leaves the previous run's rows serving."],
           tone="data")

    c.group(1492, 490, 856, 340, "The schema", "data", note="data_source sits inside the primary key")
    tables = [
        ("landing.import_run", "PK (id) · status · row_counts · reconciled"),
        ("landing.customer", "PK (volt_id, data_source)"),
        ("landing.order", "PK (volt_id, data_source)"),
        ("landing.customer_block", "PK (volt_id, block, data_source) · payload jsonb"),
        ("app.session_state", "PK (session_id, key) · payload jsonb"),
    ]
    for i, (name, sub) in enumerate(tables):
        c.chip(1516, 535 + i * 59, 808, 52, name, "data" if i < 4 else "domain", sub=sub)

    # ---------------- band 3 — states + failure ----------------
    c.group(52, 860, 1120, 330, "Three states, not two", "neutral")
    states = [
        ("DATABASE_URL unset", ["Unit tests · CI · a laptop with no Postgres",
                                "book_source → fixtures_sheet.json", "Store → in memory"],
         "client", "AS TODAY", "exactly as today"),
        ("Set and reachable", ["Staging.", "book_source → the landing schema",
                               "Store → app.session_state"], "data", "LIVE", "the deployed path"),
        ("Set but unreachable", ["Both refuse.", "No fixtures fallback. No memory fallback.",
                                 "That failure would look like success."], "refusal", "REFUSES",
         "REFUSING, never LEAKING"),
    ]
    for i, (t, lines, tone, badge, code) in enumerate(states):
        c.node(76 + i * 362, 905, 346, 150, t, lines, tone, code=code, badge=badge)

    c.note(76, 1070, 1072, 90,
           ["• The refusal rule applies to state 3 ONLY.",
            "• Without state 1, all 569 backend tests would need a live database, and cloudbuild's",
            "  bare python:3.12-slim test step would fail on the very first import."],
           tone="neutral")

    c.group(1192, 860, 1156, 330, "Failure → behaviour", "refusal",
            note="RUNNING and REFUSING are both honest; LEAKING is not")
    failures = [
        ("Migration fails", "debt-migrate exits non-zero — the new revision never takes traffic", "infra"),
        ("Odoo unreachable", "run recorded FAILED · degrade ODOO → last good landing rows → SHEET", "external"),
        ("Import run fails midway", "the transaction rolls back — the previous run keeps serving", "data"),
        ("Cloud SQL configured but unreachable", "the API REFUSES — no fixtures, no memory", "refusal"),
        ("Session state write fails", "refused and surfaced to the officer, never dropped silently", "refusal"),
    ]
    for i, (label, sub, tone) in enumerate(failures):
        c.chip(1216, 905 + i * 52, 1108, 46, label, tone, sub=sub)

    # ---------------- band 4 — delivery, split, gaps ----------------
    c.group(52, 1220, 900, 320, "Delivery — three waves, six streams", "domain")
    waves = [
        ("Wave 1 — two start immediately",
         ["1  Schema + migrations + debt-migrate — BLOCKS WAVE 2",
          "2  GCP provisioning scripts    ·    3  The guidebook"], "domain"),
        ("Wave 2 — parallel once stream 1 lands",
         ["4  book_source.load() and the Store swap",
          "5  --to-postgres    ·    6  Odoo rehost + pagination fix"], "api"),
        ("Wave 3",
         ["Integration · deploy · verification",
          "verify_all.sh at or above 569 / 443 / 29, no test edited"], "infra"),
    ]
    for i, (t, lines, tone) in enumerate(waves):
        c.node(76, 1265 + i * 90, 852, 80, t, lines, tone)

    c.group(972, 1220, 680, 320, "Manual, then automated", "client")
    c.node(996, 1265, 636, 122, "Arina, unavoidably",
           ["1   gcloud auth login — browser",
            "2   confirm the project id and billing",
            "3   IAP OAuth consent screen — console only",
            "4   push 7 secret values from backend/.env"],
           "client", code="after step 1, my commands run as her")
    c.node(996, 1399, 636, 122, "Automated after that",
           ["APIs · Cloud SQL + database · IAM DB users",
            "service accounts · both Jobs · Scheduler",
            "budget · schema DDL · all code · all tests",
            "the deploy"],
           "domain", code="SDK 582 installed, no account yet")

    c.group(1672, 1220, 676, 320, "Not built", "refusal", note="vs GCP Architecture v1.0")
    for i, label in enumerate(["§4.1–4.3   VPC · connector · NAT",
                               "§4.4–4.5   Load Balancer · Cloud Armor",
                               "§6.5   Memorystore Redis",
                               "§7.1–7.2   Pub/Sub · Cloud Tasks",
                               "§9.1   Identity Platform",
                               "§9.4   Cloud KMS / CMEK",
                               "§6.2   the twelve Data_Model schemas"]):
        c.chip(1696, 1265 + i * 36, 628, 32, label, "refusal")

    c.legend(52, 1585, [("estate", "infra"), ("data", "data"), ("seam / domain", "domain"),
                        ("people & manual", "client"), ("out of scope / refuses", "refusal")])
    c.footer("pictures/GCP design/06-one-page.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
