# Terminated customer archive

`/terminated` lists the latest completed termination per customer, 50 per page.
Paid-off `CLOSED` cases and customers with a live contract are excluded. Historical
snapshots remain accessible by archive UID even when a new contract is imported.
The archive screens make no mutation requests.

## Storage and safety

PostgreSQL `app.termination_fact` holds shared terminal contract statuses and
termination evidence. `app.termination_archive` holds JSON snapshots shaped and
masked by the existing case-detail API. Both tables reject updates/deletes. Each
archive records an audit request ID; audit display enrichment does not alter any
signed audit field or hash. Termination writes and snapshot capture use a shared
SQL advisory lock and one database transaction. Failure restores the acting
session's case, journey and contract overlay and returns a retryable refusal.

A second account reads terminal statuses from the same facts. A case with multiple
contracts is archived only after every contract ends, with at least one ending
other than ordinary `CLOSED`. A new set of terminated contracts can produce a new
immutable archive; the list shows one latest row per customer.

With no DATABASE_URL, the developer fallback is SQLite at
`backend/var/termination-archive.sqlite3` (override `TERMINATION_ARCHIVE_PATH`).
Configured PostgreSQL failures never fall back to SQLite.

## Migration and backfill

Take a database backup before deploying the new image. Run these using the
migration job's service account and database configuration:

```
python -m app.migrate
python -m app.termination_backfill
```

Backfill reads existing account/browser case, contract-overlay and journey stores
with a restricted legacy reader, then imported records. It writes JSON only,
retains unknown dates/actors/reasons as missing, and is safe to rerun. Existing
snapshot payloads are never overwritten. Backfill snapshots explicitly record
`capture_kind=BACKFILL` and their actual capture time. Import healing also captures
new imported terminations (`IMPORT`). Backfill runs must precede traffic switching.

## API

- GET `/v1/terminated-customers`: `q`, `since`, `until` (inclusive dates), `cause`,
  `actor`, `source`, `page`. Returns summaries and filter options.
- GET `/v1/terminated-customers/{archive_uid}`: immutable snapshot and evidence.
- GET `/v1/audit`: existing parameters plus `q`, `until` (exclusive instant),
  `outcome`; cursor paging/search runs on the server. `display` adds customer names,
  activity labels, evidenced reasons and an exact archive/case link.

Existing authentication/read access applies. There is no snapshot mutation API.
Audit calendar filters use Bangkok days. A missing target keeps its original
reference and displays that its case cannot be opened.

## Release

Build frontend into backend/static, build the image, run migration/backfill, deploy
with no traffic and a candidate tag. Check livez, readyz, authenticated listing,
archive tabs, search, audit verification, keyboard controls and narrow layout.
Only then switch staging traffic. SSH delivery applies the same scoped source
patch after a file backup; it does not rebuild or restart production.
