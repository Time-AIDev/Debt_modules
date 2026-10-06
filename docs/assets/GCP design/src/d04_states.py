"""Sheet 4 — the three states, and what each failure does."""
from hld_lib import Canvas


def build():
    c = Canvas(1680, 1330, "SHEET 4 — STATES & FAILURE",
               "Configured, unconfigured, unreachable — three states, not two",
               "Without the unconfigured path, all 569 backend tests would need a live database, and "
               "infra/cloudbuild.yaml's test step — a bare python:3.12-slim container with no Postgres "
               "— would fail on the first import.")
    c.header()

    # ------------------------------------------------------------------
    # PART 1 — the three-state matrix
    # ------------------------------------------------------------------
    c.group(52, 160, 1576, 302, "Three states, not two", "neutral",
            note="DATABASE_URL decides · backend/app/config.py")

    COLS = (220, 692, 1164)          # three state columns, 448 wide each
    CW = 448

    c.text(68, 222, "WHAT IT DOES", size=10, fill="#9aa1ac", weight=700, spacing=1.1)

    states = [
        ("1 · DATABASE_URL UNSET", "unit tests, CI, a laptop with no Postgres", "client"),
        ("2 · SET AND REACHABLE", "staging", "data"),
        ("3 · SET BUT UNREACHABLE", "the database has gone away", "refusal"),
    ]
    for x, (label, sub, tone) in zip(COLS, states):
        c.chip(x, 196, CW, 44, label, tone, sub=sub)

    # row 1 — book_source
    c.text(68, 296, "book_source", size=12.5, fill="#14161a", weight=700,
           font="'SF Mono','JetBrains Mono',Menlo,Consolas,monospace")
    c.text(68, 314, "the figures", size=10, fill="#6b7280")

    row1 = [
        ("Reads fixtures_sheet.json",
         ["Exactly as today.", "No database is opened, and none is needed."],
         "client", "fixtures_sheet.json", "AS TODAY"),
        ("Reads the landing schema",
         ["Staging.", "The rows the last good import run wrote."],
         "data", "landing", "LIVE"),
        ("REFUSES",
         ["Does not fall back to fixtures.", "This column is the only one that refuses."],
         "refusal", "DATABASE_URL set · host unreachable", "REFUSES"),
    ]
    for x, (t, lines, tone, code, badge) in zip(COLS, row1):
        c.node(x, 254, CW, 88, t, lines, tone, code=code, badge=badge)

    # row 2 — Store
    c.text(68, 398, "Store", size=12.5, fill="#14161a", weight=700,
           font="'SF Mono','JetBrains Mono',Menlo,Consolas,monospace")
    c.text(68, 416, "session state", size=10, fill="#6b7280")

    row2 = [
        ("In-memory",
         ["Exactly as today.", "A laptop with no Postgres still runs."],
         "client", "in-memory", "AS TODAY"),
        ("Reads and writes app.session_state",
         ["Staging.", "Persisted in Cloud SQL, not in the process."],
         "data", "app.session_state", "LIVE"),
        ("REFUSES",
         ["Does not fall back to memory.", "The write is surfaced, never dropped."],
         "refusal", "DATABASE_URL set · host unreachable", "REFUSES"),
    ]
    for x, (t, lines, tone, code, badge) in zip(COLS, row2):
        c.node(x, 356, CW, 88, t, lines, tone, code=code, badge=badge)

    # the two things the sheet must say out loud
    c.note(52, 478, 780, 104,
           ["• A database that is configured and unreachable is the only",
            "  case that refuses. States 1 and 2 both serve figures.",
            "• In state 3 book_source refuses and Store refuses. Neither",
            "  degrades to fixtures, and neither degrades to memory."],
           title="The refusal rule applies to state 3 only", tone="refusal")

    c.note(848, 478, 780, 104,
           ["• Without it, all 569 backend tests would need a live database.",
            "• infra/cloudbuild.yaml's test step is a bare python:3.12-slim",
            "  container with no Postgres — it would fail on the first import.",
            "• So state 1 is what keeps the test contract and CI intact."],
           title="The unconfigured path is not a convenience", tone="client")

    # ------------------------------------------------------------------
    # PART 2 — the failure table
    # ------------------------------------------------------------------
    c.group(52, 608, 1576, 370, "What each failure does", "infra",
            note="five failures, five behaviours")

    C1, C2, C3 = 68, 414, 1360       # failure · what happens · verdict
    for x, head in ((C1, "FAILURE"), (C2, "WHAT HAPPENS"), (C3, "VERDICT")):
        c.text(x, 656, head, size=10, fill="#9aa1ac", weight=700, spacing=1.1)
    c.line(68, 664, 1612, 664, stroke="#d9dce2")

    rows = [
        ("Migration fails", "debt-migrate",
         "debt-migrate exits non-zero; the new revision never takes traffic.",
         "This is exactly why cloudbuild.yaml sequences migrate before deploy-api.",
         "never takes traffic", "infra"),
        ("Odoo unreachable, or refuses the login", "ODOO → landing → SHEET",
         "The run is recorded FAILED. Serving degrades ODOO → last good landing rows → SHEET.",
         "No partial overwrite.",
         "no partial overwrite", "external"),
        ("Import run fails midway", "import_run.status",
         "The transaction rolls back; the previous run keeps serving.",
         "import_run.status='FAILED', with the reason.",
         "previous run keeps serving", "data"),
        ("Cloud SQL configured but unreachable", "DATABASE_URL",
         "The API REFUSES.",
         "It does NOT fall back to fixtures or to memory.",
         "REFUSES", "refusal"),
        ("Session state write fails", "app.session_state",
         "The write is refused and surfaced to the officer.",
         "Never dropped silently.",
         "REFUSES, VISIBLY", "refusal"),
    ]
    for i, (name, code, a, b, verdict, tone) in enumerate(rows):
        top = 672 + i * 58
        c.text(C1, top + 20, name, size=11.5, fill="#14161a", weight=650)
        c.text(C1, top + 37, code, size=10, fill="#9aa1ac",
               font="'SF Mono','JetBrains Mono',Menlo,Consolas,monospace")
        c.text(C2, top + 20, a, size=11, fill="#14161a")
        c.text(C2, top + 37, b, size=11, fill="#6b7280")
        c.chip(C3, top + 10, 252, 30, verdict, tone)
        if i < len(rows) - 1:
            c.line(68, top + 58, 1612, top + 58, stroke="#d9dce2")

    # ------------------------------------------------------------------
    # PART 3 — the governing principle
    # ------------------------------------------------------------------
    c.group(52, 1004, 1576, 206, "The governing principle", "refusal",
            note="backend/app/config.py already defines all three")

    principles = [
        (68, "RUNNING", ["A declared default is live", "and producing figures."],
         "domain", "HONEST"),
        (592, "REFUSING", ["The engine stops.", "Nothing is written."],
         "refusal", "HONEST"),
        (1116, "LEAKING", ["The slot is empty and a figure", "renders anyway, from elsewhere."],
         "external", "NOT HONEST"),
    ]
    for x, t, lines, tone, badge in principles:
        c.node(x, 1040, 496, 88, t, lines, tone, badge=badge)

    c.text(840, 1168, '"RUNNING and REFUSING are both honest, and LEAKING is not."',
           size=19, fill="#14161a", weight=700, anchor="middle")
    c.text(840, 1191,
           "A configured database that has gone away must never degrade to fixtures or to "
           "memory, because that failure would look exactly like success.",
           size=11.5, fill="#6b7280", anchor="middle")

    c.legend(52, c.h - 75, [("unconfigured — as today", "client"),
                            ("configured & reachable", "data"),
                            ("refuses", "refusal"),
                            ("failure path", "infra"),
                            ("leaking — not honest", "external")])
    c.footer("pictures/GCP design/04-states-and-failure.svg  ·  src/render.py  ·  generated 2026-09-10",
             right="Volt Debt — GCP staging design")
    return c
