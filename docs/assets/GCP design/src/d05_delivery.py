"""Sheet 5 — delivery waves, the manual/automated split, and the gap list."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1710, "SHEET 5 — DELIVERY & GAPS",
               "Three waves, six streams, and what is deliberately not built",
               "Each gap is named with what adding it would take, so promotion to production is an "
               "addition set rather than a rewrite.")
    c.header()

    # ------------------------------------------------------------------
    # BLOCK 1 — the waves
    # ------------------------------------------------------------------
    c.group(52, 160, 600, 367, "Wave 1", "domain",
            note="three streams · two start immediately")
    W1 = [("1 · Schema + migrations",
           ["The debt-migrate job entrypoint",
            "Nothing in wave 2 can start until this lands"],
           "debt-migrate", "BLOCKS WAVE 2"),
          ("2 · GCP provisioning",
           ["Scripts that stand up the topology"],
           "the topology", None),
          ("3 · The guidebook",
           ["Written into an Obsidian vault"],
           "an Obsidian vault", None)]
    for i, (t, lines, code, badge) in enumerate(W1):
        c.node(68, 205 + i * 106, 568, 90, t, lines, "domain", code=code, badge=badge)

    c.group(692, 160, 600, 367, "Wave 2", "api",
            note="all three parallel once stream 1 lands")
    W2 = [("4 · The Store swap",
           ["book_source.load(), and the Store swap"],
           "book_source.load()"),
          ("5 · Master sheet into Postgres",
           ["The importer gains a Postgres target"],
           "import_master_sheet.py --to-postgres"),
          ("6 · Odoo rehost",
           ["Plus the 500-partner pagination fix"],
           "the pagination fix")]
    for i, (t, lines, code) in enumerate(W2):
        c.node(708, 205 + i * 106, 568, 90, t, lines, "api", code=code)

    c.group(1332, 160, 296, 367, "Wave 3", "infra", note="sequential")
    for i, label in enumerate(["Integration", "Deploy", "Verification"]):
        c.chip(1348, 226 + i * 106, 264, 48, label, "infra")

    # stream 1 blocks wave 2
    c.arrow([(642, 250), (686, 250)], label="blocks", tone="refusal",
            sw=2.0, label_dy=-14)
    # wave 2 hands to wave 3
    c.arrow([(1298, 250), (1328, 250)], tone="infra", sw=1.6)

    # ------------------------------------------------------------------
    # BLOCK 2 — manual vs automated
    # ------------------------------------------------------------------
    c.note(52, 567, 1576, 44,
           ["• Once Arina runs gcloud auth login, subsequent gcloud commands run as her. "
            "That single fact is what draws the line between these two columns."],
           tone="external")

    c.group(52, 635, 760, 241, "Arina, unavoidably", "external", note="four items")
    M = [("1 · Authenticate", ["Browser-interactive"], "gcloud auth login"),
         ("2 · Confirm the project", ["The project id, and that billing is live"], None),
         ("3 · IAP OAuth consent screen", ["Console-only. No API covers it"], None),
         ("4 · Push the seven secret values",
          ["The command reads backend/.env directly,",
           "so no value is echoed into a transcript"], None)]
    for i, (t, lines, code) in enumerate(M):
        col, row = i % 2, i // 2
        c.node(68 + col * 368, 680 + row * 96, 356, 80, t, lines, "external", code=code)

    c.group(832, 635, 796, 241, "Automated after authentication", "infra",
            note="eleven things, no console")
    AUTO = ["API enablement", "Cloud SQL instance + database", "IAM database users",
            "Service accounts + bindings", "Both Cloud Run Jobs", "The Scheduler jobs",
            "The budget", "Schema DDL", "All application code", "All tests", "The deploy"]
    for i, label in enumerate(AUTO):
        col, row = i % 3, i // 3
        c.chip(848 + col * 260, 682 + row * 42, 244, 34, label, "infra")

    c.note(52, 896, 1576, 82,
           ["• gcloud SDK 582.0.0 is installed at ~/google-cloud-sdk — with NO credentialed accounts.",
            "• terraform is not installed. docker is not installed."],
           title="Verified machine state", tone="neutral")

    # ------------------------------------------------------------------
    # BLOCK 3 — the gap list
    # ------------------------------------------------------------------
    c.group(52, 1018, 1576, 455, "The gap list — not built", "refusal",
            note='against "GCP Architecture v1.0"')
    GAPS = [
        ("§4.1–4.3", "VPC  ·  Serverless VPC connector  ·  Cloud NAT",
         "Needed before any private-IP service other than Cloud SQL, and before fixed NAT egress "
         "IPs for the Odoo droplet firewall"),
        ("§4.4–4.5", "Load Balancer  ·  Cloud Armor",
         "Needed for a public origin, WAF rules, or a custom domain with managed certs"),
        ("§6.5", "Memorystore Redis",
         "Add when rate limiting lands"),
        ("§7.1–7.2", "Pub/Sub  ·  Cloud Tasks",
         "Needed for the n8n gateway and the transactional outbox"),
        ("§9.1", "Identity Platform",
         "Needed for per-user identity, the blocking function, iam_user provisioning"),
        ("§9.4", "Cloud KMS / CMEK",
         "Required for production"),
        ("§6.2", "The twelve Data_Model schemas",
         "That is the MVP build"),
    ]
    for i, (sec, comp, need) in enumerate(GAPS):
        y = 1063 + i * 58
        c.chip(68, y, 104, 34, sec, "refusal")
        c.text(192, y + 15, comp, size=12.5, weight=650)
        c.text(192, y + 31, need, size=11, fill="#6b7280")
        if i < len(GAPS) - 1:
            c.line(68, y + 44, 1612, y + 44)

    # ------------------------------------------------------------------
    # the test contract
    # ------------------------------------------------------------------
    c.note(52, 1499, 1576, 96,
           ["• Baseline 569 backend / 443 frontend (33 files) / 29 e2e. "
            "./scripts/verify_all.sh is the authority.",
            "• Adding tests is free. A test that must change is escalated to Arina, NEVER edited.",
            "• If a stream cannot proceed without an edit, that stream stops and asks."],
           title="The test contract", tone="domain")

    c.legend(52, c.h - 75, [("wave 1 · schema, infra, docs", "domain"),
                            ("wave 2 · parallel streams", "api"),
                            ("wave 3 · ship", "infra"),
                            ("Arina, unavoidably", "external"),
                            ("not built", "refusal")])
    c.footer("pictures/GCP design/05-delivery-and-gaps.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
