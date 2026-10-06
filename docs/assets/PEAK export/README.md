# PEAK export — sample evidence (local only, never commit)

Three files, two documents — measured in
`docs/archive/superpowers/plans/2026-09-11-peak-upload-payment-position.md` §0:

- `ใบแจ้งหนี้.pdf` — invoice IVT-20260700089 (฿13,060.45)
- `ใบเสร็จ (1).pdf` + `ใบเสร็จ (2).pdf` — byte-identical copies of receipt
  RE-20260700272 (฿38,257.45, settles four invoices)

Both PDFs are single-JPEG scans with **no text layer** (no OCR, no PDF text
extraction — plan constraint). The receipt is the pivotal finding: a PEAK
receipt naming the four invoices it cleared (ruling D-B, OD-02 authority).

**PDPA:** these carry an unmasked 13-digit citizen ID, full address, phone and
email. Held locally as plan evidence only — `*.pdf` in this folder is
gitignored. Do not commit, copy into fixtures, or log.
