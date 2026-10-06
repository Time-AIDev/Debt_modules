# Kickoff prompt for Claude Code

Paste this as your first message in Claude Code, from the repository root, with
`design_handoff_volt_debt_console/` present in the repo (or attached).

---

I'm implementing a redesign of the Volt Debt officer console in this repository. The
design reference is `design_handoff_volt_debt_console/` — read `README.md` there first,
then open `Volt Debt - Final v2.dc.html` in a browser and click through it. The
screenshots in `screenshots/` show all twelve screens at 1440px.

The HTML file is a **design reference**, not code to copy. Rebuild the designs in this
app's existing environment: React + Vite under `frontend/`, `react-router-dom` routes
in `src/App.jsx`, data through `src/api.js`, copy through `useT()` and the
`src/i18n-*.js` tables, preferences through `readPref`/`writePref` in `src/prefs.jsx`,
and the components already in `src/components/`. Reuse the tokens in `src/tokens.css` —
do not introduce new colour values beyond the dark-theme block the README specifies.

Before writing code, do these three things and report back:

1. **Read the current implementation** of `src/components/Shell.jsx`,
   `src/screens/Dashboard.jsx`, `src/screens/ReviewQueue.jsx`,
   `src/screens/InvoicePipeline.jsx`, `src/screens/Payments.jsx`,
   `src/screens/Recovery.jsx`, `src/screens/Settings.jsx` and `src/tokens.css`, and
   tell me where the design conflicts with a rule already encoded in the code or its
   tests (there are `*.test.jsx` files next to most screens, and several encode
   product rulings — e.g. the rail group assertions in `Shell.test.jsx`). I want the
   conflicts named before anything changes.

2. **List the data the design needs that the API does not serve yet.** I know of:
   per-officer performance (cases, arrears, receipts, contact rate, PTP kept rate, NPL
   count, today's queue), team contact success rate, DSO, and NPL roll-rate in/out for
   the Overview; and a per-setting "locked pending ruling" flag for Settings. Check
   `src/api.js` and the backend under `backend/app/` and tell me what else is missing
   and where it would come from.

3. **Propose the PR sequence.** The README suggests one; adjust it to what this
   codebase makes cheap or expensive, and keep each PR independently shippable.

Then implement in that order, one PR at a time, stopping after each for review. Rules
for the whole job:

- Keep the existing rail structure and its three group labels. The redesign changes
  geometry and behaviour, not the information architecture of the nav.
- Every role or rule refusal must stay visible and explain itself — disable the control
  and show the reason. Do not hide controls a role cannot use.
- Reject, Move date and Export require a reason; do not let them save without one.
- Locked settings cannot be edited at any role. Unlocked settings cannot be edited
  below Manager. Both states must be visible at once (officer column / manager column).
- Internal ruling codes (CF1, OD-02, OD-04, OD-31, SVC-37, DEBT-*, C5/R12) stay in the
  code, the API and the action log, and stay **out of** user-facing copy.
- Never compose a sentence and then translate the whole string. Branch on language at
  composition time. Counts, day values and amounts appear inside most sentences in this
  UI.
- Customer names, document ids and lot codes are not translated.
- Add tests alongside each screen in the style already used in this repo, and make the
  acceptance checks at the end of the handoff README pass.
- Every write action must land a row in the action log with the signing role.

Ask me before changing any API contract or any rule that a test currently asserts.
