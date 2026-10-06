"""The use-case register — every bubble on sheet 00 with its actors, its entry point
and what it writes. The diagram stays readable because this sheet carries the detail.
"""
from hld_lib import Canvas, MONO, MUTED, FAINT, HAIR

COLS = [
    (70, 400, "USE CASE"),
    (470, 200, "PRIMARY"),
    (670, 290, "SHARED WITH / GUARD"),
    (960, 350, "ENTRY POINT"),
    (1310, 620, "WHAT IT WRITES, AND THE RULE THAT HOLDS IT"),
]
ROW_H = 31
GROUP_H = 27

GROUPS = [
    ("Officer's day — วันนี้ · ปฏิทิน · ลูกค้า/สมุดงาน", "client", [
        ("Work the Today queue", "OFFICER", "—", "GET /v1/today · POST /today/items/{uid}:done",
         "The seven-tier order is fixed by REQ-COL-071; nothing here re-sorts it."),
        ("Log a contact & a promise", "OFFICER", "one OPEN PTP per customer",
         "POST /v1/contacts · /case-ptps/{uid}:close · :renegotiate",
         "Contact lock and allowance cap apply; a BROKEN promise routes to manager review."),
        ("Read the calendar & deadlines", "OFFICER", "—", "GET /v1/calendar",
         "Reads only stores that already hold dates; an undated item is counted, never dated."),
        ("Send a reminder batch", "OFFICER", "—", "POST /v1/today/reminders:send",
         "The batch label and offsets are recorded; a conflict is surfaced, not resolved."),
        ("Open the customer record", "ALL ROLES", "one component, every lens",
         "GET /v1/cases/by-customer/{uid}", "Money arrives as served data; the client computes none of it."),
        ("Search the book & the \u2318K palette", "ALL ROLES", "—", "GET /v1/workbook?q=",
         "The palette index is local; a customer hit comes only from served rows."),
    ]),
    ("Review & team — รอตรวจ · รายงาน", "api", [
        ("Assign a customer", "SUPERVISOR", "MANAGER · OWNER", "POST /v1/customers/{uid}/assign",
         "Writes the officer field; the audit entry names who moved it."),
        ("Answer a review", "SUPERVISOR", "MANAGER · OWNER", "POST /v1/reviews/{uid}:answer",
         "The decision and comment land, and the case effect lands in the same call."),
        ("Decide a power restriction", "SUPERVISOR", "MANAGER", "POST /v1/power-restrictions/{uid}:{act}",
         "approve · execute · reject · restore — each is one audited act, never a silent edit."),
        ("Read reports & aging", "MANAGER", "OWNER · SUPERVISOR",
         "GET /v1/reports/team · /reports/bucket-flow", "Every figure is the served payload; nothing is recomputed to look better."),
        ("Read & verify the audit chain", "OWNER", "OPS", "GET /v1/audit · /v1/audit/verify",
         "INTACT and COMPLETE are separate answers; a memory chain says persisted = false."),
        ("Publish the weekly edition", "OWNER", "—", "POST /v1/reports/weekly:publish",
         "Freezes the payload into an edition; an export re-formats it and never recomputes."),
    ]),
    ("Pipeline & payments — ใบแจ้งหนี้ก่อนติดตั้ง · เงินเข้าและ PEAK", "domain", [
        ("Clear gates & attach evidence", "OFFICER", "pipeline role",
         "POST /v1/pipeline/{uid}/gates/* · /conditions/{key}/evidence",
         "Down payment and EPC confirmation are gates; evidence has a remove path, not a delete."),
        ("Release the invoice", "MANAGER", "role-aware: meta.invoice_owner_role",
         "POST /v1/pipeline/{uid}:release", "Includes Create a PEAK draft; delivery and install outcome follow it."),
        ("Record a slip or credit note", "MANAGER", "OWNER", "POST /v1/slips · /v1/credit-notes",
         "Each includes a PEAK draft: the local document record is the record."),
        ("Manage PEAK documents", "OFFICER", "resubmit is MANAGER+",
         "POST /peak-documents/{uid}:resend · :refresh · /resubmit",
         "State is UNKNOWN until INT-05 answers, so the screen says check PEAK rather than guess."),
        ("Simulate PEAK — stub", "OWNER", "development only", "POST /v1/peak-documents/stub",
         "Drives the transport without credentials; it is never a production path."),
        ("Raise a service issue", "OFFICER", "responsible team", "POST /v1/service-issues",
         "The issue carries a deadline, a resolution note and the fee-clock effect."),
    ]),
    ("Recovery — NPL และการเรียกคืน", "refusal", [
        ("Declare NPL / advance the ladder", "MANAGER", "OWNER may skip, with a note",
         "POST /v1/cases/{uid}:advance", "Ladder stages are contractual ACTS moved by humans; the engine only computes a rung."),
        ("Choose a recovery path", "OFFICER", "MANAGER",
         "POST /v1/npl-cases/{uid}/recovery", "Strategy comes from RECOVERY_STRATEGIES; the rate is badged an assumption (OQ-31)."),
        ("Record a recovery", "OFFICER", "MANAGER",
         "POST /recovery-cases/{uid}/recoveries · :resolve", "CLOSED_WRITE_OFF is OWNER-only; the receipt itself is originated through Create a PEAK draft."),
        ("Manage repossession lots", "OPS", "price is OPS or OWNER",
         "POST /repossession-lots/{uid}:count/:grade/:price/:sell", "PLANNED → … → SOLD is a visible state machine; a sold lot cannot be walked back."),
        ("Restructure & approve", "OFFICER proposes", "MANAGER or OWNER approves",
         "POST /cases/{uid}/restructures → /restructures/{uid}:approve", "Eligibility refuses with a code and a Thai reason; :record-miss marks the break."),
        ("Decide a manager review", "MANAGER", "OWNER", "POST /v1/manager-review/{uid}:decide",
         "REPAYMENT_ARRANGEMENT creates an arrangement; breaking it is an act of its own."),
    ]),
    ("Data & governance — แหล่งข้อมูล · ตั้งค่า · บันทึกการใช้งาน", "data", [
        ("Sign in", "ALL HUMAN ROLES", "seven allow-listed addresses",
         "POST /v1/auth/google · /auth/password · /auth/logout", "Anyone else gets the served not_on_allow_list refusal."),
        ("Pull or upload the book", "OPS", "OWNER", "POST /v1/pipelines/crm-lead:run",
         "Three doors, one landing shape; without DATABASE_URL it refuses database_required."),
        ("Create a PEAK draft", "system", "\u00abinclude\u00bb: release · slip · recovery",
         "peak_documents.py · integrations/peak.py", "23 intents; entity + company_id pick EPC or SPV; draft-only (P3 / C3)."),
        ("Run & apply a PEAK report", "OPS", "MANAGER · OWNER",
         "POST /peak-pipeline/report:run · /landing-runs/{id}:apply", "A run is staged when written and applied by a person; door 2 is unverified and says so."),
        ("Configure settings & dictionaries", "OWNER", "—",
         "PUT /v1/config · /dictionaries/{name}/values · /band-sets", "The open decisions (CF1…SVC-37) render as declared defaults, always badged."),
        ("Take the book out", "MANAGER", "OWNER", "POST /v1/workbook:export (reason \u2265 8 characters)",
         "The receipt names who took it and why; the GET is the ungoverned read."),
        ("Receive a payment advice", "system", "automatic · no actor",
         "POST /v1/webhooks/peak/payments", "Recorded unallocated and raised as an ACC exception; allocation is never guessed (OD-02)."),
    ]),
]

X = [c[0] for c in COLS]


def build():
    c = Canvas(1980, 1560, "USE CASES · REGISTER",
               "Every use case, its actors, its entry point, and the rule that holds it",
               "The same order as the overview: five groups, one row per bubble. Roles are the "
               "X-Volt-Role values; entry points are the addresses that serve the act.")
    c.header()

    # table header
    c.rect(52, 176, 1876, 34, rx=6, fill="#eef1f6", stroke=HAIR, sw=1.1)
    for x, w, label in COLS:
        c.text(x + 10, 197, label, size=10, fill="#465061", weight=800, spacing=0.8)
    y = 210

    for title, tone, rows in GROUPS:
        c.rect(52, y, 1876, GROUP_H, rx=5, fill="#f3f6fd", stroke=None)
        c.text(64, y + 18, title, size=11.5, fill="#2f5fbe", weight=700)
        y += GROUP_H
        for i, (name, primary, shared, entry, note) in enumerate(rows):
            if i % 2:
                c.rect(52, y, 1876, ROW_H, rx=0, fill="#fafbfd", stroke=None)
            c.line(52, y + ROW_H, 1928, y + ROW_H, stroke="#eceef2", sw=1)
            c.text(X[0] + 10, y + 20, name, size=11, fill="#14161a", weight=650)
            c.text(X[1] + 10, y + 20, primary, size=10, fill="#2f5fbe", weight=700)
            c.text(X[2] + 10, y + 20, shared, size=10, fill=MUTED)
            c.text(X[3] + 10, y + 20, entry, size=9.5, fill="#0d7f63", font=MONO)
            c.text(X[4] + 10, y + 20, note, size=10, fill="#14161a" if tone != "refusal" else "#6b7280")
            y += ROW_H

    c.line(52, y + 4, 1928, y + 4, stroke=HAIR, sw=1.2)
    c.note(52, y + 22, 900, 92,
           ["Not drawn on sheet 00 because they belong to another lens: personal calendar",
            "notices (POST /v1/calendar/notices — one owner, never shared), attachments",
            "(upload · download · delete), and the read-mostly intercompany and cancellation views."],
           tone="neutral")
    c.note(980, y + 22, 948, 92,
           ["A line on sheet 00 means the actor may START the use case, not that every call succeeds:",
            "the guard column above decides each time, and the refusal renders verbatim from the",
            "RFC 9457 envelope (code · message_th · errors[]). A per-session store means one tester",
            "never sees another tester’s work — isolation, not authentication."],
           tone="refusal")

    c.legend(52, 1470, [("client act", "client"), ("workflow / reports", "domain"),
                        ("PEAK · outside", "external"), ("governed / open decision", "refusal"),
                        ("data intake", "data"), ("configuration", "neutral")])
    c.footer("pictures/HLD/use-case diagram/01-use-case-register.svg  ·  src/render.py  ·  generated 2026-09-20")
    return c
