"""L5 — how it runs and how it ships."""
from hld_lib import Canvas

def build():
    c = Canvas(1680, 1010, "LAYER 5 — RUNTIME & DEPLOYMENT",
               "Three ways this runs, and the infrastructure deliberately left unapplied",
               "One Cloud Run service, not two. A split web tier has to mint an identity token for every "
               "call to a private API service, which nginx cannot do natively; one origin removes that.")
    c.header()

    def lane(y, h, label, tone, note=None):
        c.group(52, y, 1576, h, label, tone, note=note)

    # ---- laptop ----
    lane(160, 175, "On a laptop", "client", note="./scripts/run_prototype.sh")
    L1 = [("uvicorn :8000", ["backend/.venv/bin/uvicorn app.main:app", "Lifespan attempts an Odoo sync, guarded"], "the API"),
          ("vite dev :5173", ["/api proxied to 127.0.0.1:8000 with the", "prefix stripped — without it every screen 404s"], "the interface"),
          ("./scripts/verify_all.sh", ["pytest → vitest → a fresh API on :8099 →", "the black-box checks against it"], "one command"),
          ("Run pytest without -q", ["pytest.ini already sets it; passing it again", "double-suppresses into 400 bare dots"], "it read as a failure once")]
    for i, (t, lines, code) in enumerate(L1):
        c.node(80 + i * 388, 205, 340, 110, t, lines, "client", code=code)

    # ---- UAT ----
    lane(365, 175, "For a UAT round", "domain", note="never the dev server")
    L2 = [("npx vite build", ["A frozen production build. The round-1 judge", "tested a dev server that hot-reloaded mid-verdict"], "frontend/"),
          ("vite preview :5173", ["--strictPort, so the round cannot quietly", "move to another port between testers"], "the frozen build"),
          ("uat_browser.mjs", ["Chrome for Testing under .uat-browser/,", "one profile per round, gitignored"], "puppeteer-core"),
          ("Re-enable the PEAK stub", ["A manual uvicorn start does not do it —", "POST /v1/peak-documents/stub after every restart"], "round 3's standing rule")]
    for i, (t, lines, code) in enumerate(L2):
        c.node(80 + i * 388, 410, 340, 110, t, lines, "domain", code=code)

    # ---- cloud ----
    lane(570, 175, "On Google Cloud", "infra", note="./scripts/deploy_gcp.sh · asia-southeast1")
    L3 = [("Preflight", ["Active account, billing on,", "four APIs enabled"], "run · build · registry · iap"),
          ("Verify before shipping", ["The same verify_all.sh gate", "the laptop runs"], "no green, no deploy"),
          ("Cloud Build", ["test → build api + web →", "push (infra/cloudbuild.yaml)"], "SHORT_SHA tags"),
          ("Artifact Registry", ["debt-api and debt-web images", "per commit"], "PROJECT/debt/*"),
          ("Cloud Run + IAP", ["ONE service. IAP bound to", "domain:volt.co.th"], "gcloud beta run … --iap")]
    for i, (t, lines, code) in enumerate(L3):
        c.node(80 + i * 310, 615, 280, 110, t, lines, "infra", code=code)
        if i:
            c.arrow([(80 + i * 310 - 30, 670), (80 + i * 310 - 2, 670)], tone="infra", sw=1.5)

    # ---- unapplied ----
    c.group(52, 775, 1000, 130, "Written, and deliberately unapplied", "refusal",
            note="infra/terraform/")
    for i, name in enumerate(["cloud_sql.tf", "pubsub.tf", "scheduler.tf", "secrets.tf",
                              "storage.tf", "network.tf", "iam.tf", "cloud_run.tf"]):
        col, row = i % 4, i // 4
        c.chip(76 + col * 240, 820 + row * 42, 224, 34, name, "refusal")

    c.note(1090, 775, 538, 130,
           ["• Nothing in infra/terraform is applied. It stands for the",
            "  MVP's shape, not this prototype's, and the deploy script",
            "  says so in its own header rather than in a wiki.",
            "• Credentials come from backend/.env, gitignored: the names",
            "  appear in .env.example, the values nowhere."],
           title="Why none of it is running", tone="refusal")

    c.legend(52, 935, [("laptop", "client"), ("UAT round", "domain"),
                        ("cloud", "infra"), ("unapplied", "refusal")])
    c.footer("pictures/HLD/05-runtime-and-deployment.svg  ·  src/render.py  ·  generated 2026-09-09")
    return c
