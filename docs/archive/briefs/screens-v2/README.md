# screens-v2 — the rebuilt screen set (design record)

Per R7 (grilling 2026-08-30) the rebuild is code-first and these briefs are the
design record — there is no Figma round-trip. Each brief states the screen's
purpose in the journey, its zones, its actions and their API calls, and the rules
it makes visible. The house idioms apply everywhere and are stated once here:

- **Money pair** — arrears large, outstanding small beneath; no bare numbers;
  `—` when absent; nothing summed client-side.
- **Band pair** — a bucket never renders without its `band_set_code`.
- **Entity chip** — identity, not status: outline + mono, never amber, never a
  status pair; refuses to render without the entity.
- **Ladder** — drawn only from the API's ladder object; the filled notch is the
  human-moved stage, the dashed notch the indicative rung (ASSISTED mode only).
- **Data-source chip** (R5) — SHEET/SYNTHETIC/ODOO, field-grouped identity vs
  history, so a reviewer can tell real from invented.
- **Problem** — every refusal renders the RFC-9457 document verbatim: title,
  detail, `message_th`, mono `code · error_id`.
- **PendingBadge** — every indicative figure is flagged at the figure (CF1,
  OD-04, OQ-31, SVC-37), never in a footnote.
- Amber is the brand and never a status. Tokens only — no new hex anywhere
  (`src/journey.css` composes entirely from `src/tokens.css`).

| Brief | Screen(s) | Route(s) |
| :-- | :-- | :-- |
| `01-my-day.md` | My Day — hero card + tiered queue + demoted board | `/` |
| `02-contact-drawer.md` | ContactDrawer — the officer loop (component) | (overlay) |
| `03-customer-360.md` | Customer 360 — header/ladder, arrears block, invoices+PEAK, timeline | `/customers/:uid` |
| `04-queues-review.md` | Follow-ups + Manager review | `/queues`, `/review` |
| `05-receivables.md` | NPL & recovery, Cash defaults, Service billing 37+ | `/npl`, `/cash-defaults`, `/service-billing` |
| `06-data-sources.md` | Data sources — Odoo/PEAK, overrides | `/data-sources` |

Kept screens (Exceptions, Overview, Pending decisions, Orders, Loan book, UAT,
Recovery board) are documented by their original briefs plus the changes noted in
the git log; the four `figma-*.md` briefs remain the record of Product UI v0.1.
