# screens-v2 · 03 — Customer 360 (`/customers/:customerUid`, `src/screens/Customer360.jsx`)

The customer, whole — absorbing the old Contract card's arrears discipline and
adding what the journey needs: the ladder position, the invoice/receipt record
with the PEAK write, and the merged debt timeline. **Driven by the route param**;
the old screen's bug (deriving the customer from the list's first row) is dead.
Contract selection travels in `?contract=` so a view is shareable.

## Zones

1. **Header** — breadcrumb from My Day; name at display-24; chip row (customer
   no, masked phone, EntityChip, DataSourceChip, Band, fee state, contact-slot
   state); the ladder in detail variant; the fixture-authored `order_ref` line
   with its bridge note, verbatim ("no join key exists in live data").
2. **Arrears stat strip** (`.jy-stats`, from `GET /v1/contracts/{uid}/summary` —
   REQ-COL-027 order preserved): payable today (with outstanding beneath) ·
   DPD + band · accrued penalty with the CF1 PendingBadge and the four figures
   (accrued/billed/paid/waived — never netted) · next due · full payoff labelled
   as the OD-03 fallback with the balancing-final-line note.
3. **Actions** — บันทึกผล (drawer).
4. **Contracts card** — one row per contract; the uid switches `?contract=`;
   product + status + Money + DPD/band + fee state.
5. **Invoices & receipts card** — each invoice: kind, amount, state, EntityChip
   (SERVICE-typed for service invoices); PEAK state chip (`SENT_PEAK · ref` /
   `UNSENT — local record kept`); **Issue in PEAK (UAT)** on anything unsent
   (R15) → `POST /v1/invoices/{uid}:issue-peak`; the returned `qr_payload`
   renders as a mono block. Receipts show amount, match state and the standing
   "allocation pending OD-02". A `peak_unsent` failure renders verbatim.
6. **Debt timeline** — `GET /v1/customers/{uid}/timeline`, newest first: date ·
   type (INVOICE/RECEIPT/PTP/CONTACT/LADDER/INTERCOMPANY) · one-line summary.
   When the customer holds a service account, the quiet Notice above it states
   the isolation rule (service arrears never feed the lease ladder).

## Data

working-list (header chips + ladder), customerContracts, contractSummary,
contractInvoices/Receipts, timeline. Legacy `/contracts/:uid` still mounts the
old ContractCard as the record of the v0.1 build target.
