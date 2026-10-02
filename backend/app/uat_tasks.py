"""The task script for a UAT feedback round.

Tasks, not a tour. "Have a look and tell me what you think" produces opinions about
colour; "approve the three Bangkok orders over 3,000 baht and tell me where you
hesitated" produces findings.

Two rules each task obeys:
  - It names what we are trying to LEARN, separately from what to do. A tester who
    knows the question gives a better answer than one guessing at it.
  - It does not lead. No task says "notice how clear X is". Several deliberately
    send a tester at a screen that REFUSES, because whether the refusal reads as
    deliberate or as a fault is exactly what we do not know.

`answer` is what the build currently does, for whoever reads the feedback
afterwards. It is never shown to the tester before they attempt the task.
"""

TASKS = [
    {
        "id": "T1", "route": "/orders", "screen": "orders",
        "title": "Approve the order for Chayakan Chupanya",
        "do": "Find that customer in the queue and move the order to Order - Done.",
        "learn": "Whether the queue is searchable the way an officer expects, and "
                 "whether the approve control is where they look for it.",
        "answer": "Search accepts name, CRM id or province. Approve sits at the row's right edge.",
    },
    {
        "id": "T2", "route": "/orders", "screen": "orders",
        "title": "Add an order, then remove it",
        "do": "Create an order for a customer of your own invention, then remove it again.",
        "learn": "Whether the required fields match what an officer actually has to "
                 "hand at that moment, and whether removal feels safe enough to use.",
        "answer": "First name, last name and CRM id are required. Removal asks to confirm "
                  "and states that the source sheet is not written to.",
    },
    {
        "id": "T3", "route": "/orders", "screen": "orders",
        "title": "Find an order that is paid in one go rather than monthly",
        "do": "Locate a Cash order and say what it costs and over how long.",
        "learn": "Whether the one-off versus per-month distinction reads at a glance. "
                 "The sheet stores both in the same column, which is where this goes wrong.",
        "answer": "Cash rows read one-off and no term; leasing rows read per month with a term.",
    },
    {
        "id": "T4", "route": "/loan-book", "screen": "loan-book",
        "title": "Check the lease you just created",
        "do": "Open the loan book and find the lease your approval produced. Say what "
              "it is missing compared with the ones above it.",
        "learn": "Whether not carried reads as missing data or as a fault in the app.",
        "answer": "Book value and commencement date read not carried: tab x does not supply them.",
    },
    {
        "id": "T5", "route": "/overview", "screen": "overview",
        "title": "Set the review up for how you work",
        "do": "Choose the population you care about, set a target for approvals, and "
              "save it as your default.",
        "learn": "Whether saving a default feels like a personal setting or like "
                 "changing something for everybody. They are different, and the app "
                 "claims it is the former.",
        "answer": "The default is yours alone and is labelled with who saved it and when.",
    },
    {
        "id": "T6", "route": "/overview", "screen": "overview",
        "title": "Say which number you would take to a board meeting",
        "do": "Look over the figures and pick one you would be willing to defend. "
              "Then pick one you would not.",
        "learn": "Whether no target set reads as an honest gap or as an unfinished screen.",
        "answer": "Every figure is measured. Only the ones with a target show progress.",
    },
    {
        "id": "T7", "route": "/", "screen": "today-list",
        "title": "Decide who to call first",
        "do": "From the today list, choose the customer you would contact first and "
              "say why.",
        "learn": "Whether priority, arrears and days past due point at the same person, "
                 "and which one an officer actually trusts.",
        "answer": "P1 is most urgent. Arrears is the large figure, outstanding the small one beneath.",
    },
    {
        "id": "T8", "route": "/exceptions", "screen": "exceptions",
        "title": "Open the exceptions dashboard",
        "do": "Go to Exceptions and try to read the figures.",
        "learn": "Whether the refusal reads as deliberate or as broken. The screen shows "
                 "nothing until a population is chosen, on purpose.",
        "answer": "It refuses until a population filter is chosen. There is no whole-book default.",
    },
    {
        "id": "T9", "route": "/pending", "screen": "open-decisions",
        "title": "Find a number the system is using that nobody has agreed",
        "do": "Open Open decisions and name one value that is affecting figures elsewhere "
              "in the app right now.",
        "learn": "Whether the difference between refusing and rendering anyway lands.",
        "answer": "Three render anyway: early settlement method, NPL DPD threshold and discount rate. One refuses: allocation component order.",
    },
    {
        "id": "T10", "route": "/orders", "screen": "any",
        "title": "Switch the interface to the language and theme you would use daily",
        "do": "Change the language and the theme in the top right, then carry on working "
              "for a minute.",
        "learn": "Whether anything is untranslated, clipped or unreadable once switched. "
                 "Thai runs longer than English and the layouts were drawn in English.",
        "answer": "Thai is the default. Some long explanatory prose is still English.",
    },
    # --- the 2026-08-30 rebuild: the journey round ---------------------------------
    {
        "id": "T11", "route": "/", "screen": "my-day",
        "title": "Work the first call the screen hands you",
        "do": "Open My Day, take the hero card's customer, press บันทึกการติดต่อ, log an "
              "ANS_DISCUSSED with a promise for next week, then follow the ถัดไป button.",
        "learn": "Whether the hero-card-first layout (R9) matches how you actually start "
                 "a morning, and whether the counting-cost wording on the option reads "
                 "before it bites.",
        "answer": "The hero is the tiered queue's winner. The counting options carry the "
                  "slot cost; an amount stated spends it immediately.",
    },
    {
        "id": "T12", "route": "/", "screen": "my-day",
        "title": "Say why the second customer in the queue is second",
        "do": "Read the queue and explain the order out loud, then check your answer "
              "against the reason chips.",
        "learn": "Whether the tier rule (PTP due today → biggest arrears → deepest "
                 "ladder → broken PTP) is legible from the chips alone (R11).",
        "answer": "Every row carries a priority_reason chip naming the tier that won.",
    },
    {
        "id": "T13", "route": "/queues", "screen": "queues",
        "title": "Break a promise and see where it lands",
        "do": "In the PTP due tab, mark the due promise ผิดนัด, then find the customer "
              "again in the app.",
        "learn": "Whether the broken-PTP → Manager Review routing (flow part 3) is "
                 "discoverable without training.",
        "answer": "Closing BROKEN opens a review; the customer shows an 'in review' tag "
                  "and appears in /review.",
    },
    {
        "id": "T14", "route": "/review", "screen": "manager-review",
        "title": "Decide one review, and explain why a cash case offers fewer buttons",
        "do": "Open Manager review, decide the broken-promise case, then open the cash "
              "customer's case and compare the available decisions.",
        "learn": "Whether the evidence panel carries what a manager actually weighs, and "
                 "whether the missing restructure button on cash reads as a rule or a bug.",
        "answer": "Cash accounts follow S11 (30/60/90 → legal or removal); restructure "
                  "and lease-NPL do not exist for them, and the screen says so.",
    },
    {
        "id": "T15", "route": "/npl", "screen": "npl",
        "title": "Price Dan's lot and sell it",
        "do": "Find lot RP-2026-0148, try to sell it, then price it as Dan and sell it.",
        "learn": "Whether the blocked-until-priced rule reads as protection or "
                 "obstruction, and whether the variance line is alarming enough.",
        "answer": "Selling refuses until a price is saved by Dan; the sale lands on the "
                  "recovery case's total. 12 went up, 11 came back — the variance needs "
                  "a reason and a photo.",
    },
    {
        "id": "T16", "route": "/service-billing", "screen": "service-billing",
        "title": "Try to bill this month's service fee",
        "do": "On the month-39 account, press the bill button and read what comes back.",
        "learn": "Whether the 25th–30th window refusal reads as the law it is (deck S09) "
                 "or as an error, on the 23rd.",
        "answer": "It refuses with billing_window_closed: ALL service billing is raised "
                  "on the 25th to 30th. The open question on declining the month-37 service contract is flagged beside it.",
    },
]

# What a tester must be told before they start, or their feedback lands on the wrong
# things. Every line is a real property of this build.
LIMITATIONS = [
    "Penalty figures use the rate Arina decided on 2026-09-09: 0.03 %/day. "
    "PEAK still bills 0.3 %/day, so a figure here reads one tenth of the customer's own "
    "tax invoice until AR moves PEAK's setting.",
    "Customer contact details are masked and map pins are removed. The names and "
    "deal figures are real.",
    "Your work is private to your browser and is not saved. Closing the tab or a "
    "redeploy clears it. Nothing you do here reaches the source spreadsheet, Odoo or PEAK.",
    "Some longer explanatory text is still in English even with Thai selected.",
    "This is a prototype, not the finished system. Several screens refuse to answer "
    "on purpose rather than show a number nobody has agreed.",
]


def tasks(include_answers=False):
    if include_answers:
        return TASKS
    return [{k: v for k, v in t.items() if k != "answer"} for t in TASKS]
