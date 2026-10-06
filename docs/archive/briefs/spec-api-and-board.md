---
title: Spec extract — API surface, collections board rules and KPI definitions
purpose: Implementation brief for the Volt Debt prototype
source_repo: /Users/parattakorn/volt-debt-collection (LOCAL, read 2026-08-26)
sources_read:
  - docs/08-api/API_Surface.md (2538 lines, version 1.0, date 2026-08-21)
  - docs/00-prd/PRD.md (809 lines, version 1.0)
  - docs/03-integrations/Event_Contracts.md (1116 lines, version 1.0)
  - docs/07-testing/TEST-CASES-COL.md (206 lines, version 1.0)
  - docs/07-testing/TEST-CASES-KPI.md (183 lines, version 1.0)
  - supporting reads: docs/06-workflow/Collection_Workflow_Alignment.md §5.2, docs/03-integrations/PEAK_Integration.md §7.3
status: extract, not a new contract — where this brief and the spec disagree, the spec wins
---

# Spec extract — API surface, collections board rules, KPI definitions

> **v1.0 EXTRACT — baseline, ladder rank 7 (banner added 2026-08-30).** Read with `spec-deltas-v21-v24.md` and `spec-deltas-v25-rebuild.md`; the ladder in the latter governs. The board rules (§7) and KPI definitions (§8) remain in force; the endpoint catalogue predates the rebuild's ~35 new journey endpoints.

Everything below is drawn from the LOCAL spec repo. Blockquotes and fenced blocks are verbatim; prose outside them is summary. Section 12 lists the places where the spec contradicts itself or where the request did not match what is in the repo — read that section before building anything shaped like a contract.

---

## 0. Jargon and codes, for a first-time reader

| Term | What it means here |
|---|---|
| DPD | Days past due. `null` while a contract is PRE_COLLECTION, `0` once collection begins — never conflate the two. |
| Aging bucket | Current 0, Early Overdue 1–7, Mid Overdue 8–29, Risk Review 30+, NPL Confirmed, Resolved, Closed. |
| Today List | The daily work queue, built by a 02:30 Asia/Bangkok batch job, grouped by **customer**, ranked priority 1 (highest) to 6. |
| Daily lock / daily slot | The Thai Debt Collection Act rule: at most one *counting* collection contact per customer per calendar (Bangkok) day. A "slot" is that one permission; unsuccessful attempts do not spend it. |
| Counting contact | A contact that consumes the daily slot. Determined server-side by the guard, never by the UI. |
| NOTIFICATION vs COLLECTION_CONTACT | Two message categories. NOTIFICATION (reminders, invoices, receipts) never counts and is unlimited-ish. COLLECTION_CONTACT is manual officer outreach and is rate-limited by law. |
| PTP | Promise to pay. Classified from the *allocation*, never from a raw amount received. |
| Hold | Three types: CONTACT_HOLD (stops outbound contact), LEGAL_HOLD (records a legal position, does **not** stop contact), PENALTY_SERVICE_HOLD (freezes DPD and penalty accrual). |
| Payment claim | An uploaded bank-slip assertion that money moved. PENDING until Accounting confirms against a PEAK receipt. **Never moves DPD.** |
| Posting / posting exception | A money row Debt sends to PEAK (the accounting system). A failure becomes an exception row on the Accounting exception dashboard. |
| Recovery case / recovery path | After NPL, the set of open recovery tracks A/B/C/D on a contract. A *set*, never a single column. |
| Module codes | INT intake, MNY money, COL collections, MOD modifications/recovery, ACC accounting sync, DOC documents, IAM identity, CFG config, AUD audit, KPI indicators, PLT platform. |
| `uid` | Public identifier on every resource: UUID v7, time-ordered. The only thing that appears as a path parameter. |
| IK / IM | Shorthand used in the spec's own tables: `Idempotency-Key` required / `If-Match` required. |
| SPV / EPC | The two legal entities. Only SPV resolves to a PEAK adapter at MVP; EPC returns 422 `entity_unresolved`. |

---

## 1. Version status — read this first

**The request said "the doc version moved to v2.x but the HTTP surface deliberately stays /v1". In the LOCAL repo that is only half true, and the half that is true is stated differently than expected.**

What the local repo actually contains, verified:

- Every doc in `/Users/parattakorn/volt-debt-collection/docs/` carries `version: 1.0` in frontmatter — PRD, API_Surface, Event_Contracts, Data_Model, Collection_Workflow_Alignment, Operations_Runbook, both test-case files. `grep -rn '^version: 2' docs/` returns **nothing**.
- `API_Surface.md` frontmatter: `version: 1.0`, `date: 2026-08-21`, `status: Draft`.
- Git history is three commits, last docs commit `80a1868 docs: complete the design package`.

So the v2.1 revisions live somewhere else (Drive), not in this repo. **Do not cite the local repo as evidence of a v2.x document.**

What the local text *does* say, verbatim, is the doc-version-versus-wire-version rule, which is the substance behind the request. Three quotes, all from `API_Surface.md`:

§2.1, base path row:

> Base path | `/v1` for every business endpoint; `/v1/webhooks/*` for inbound integrations; `/internal/*` for Google-signed machine callers only (never routed by the load balancer); `/healthz`, `/readyz`, `/api/healthz`, `/api/readyz` for probes

§6.1, `info.version` row:

> The running application version from `GET /v1/meta/version`, for example 1.4.2. **The API contract version is the path segment `/v1`; `info.version` tracks the build so a client can tell which build produced a document**

§6.8, "Contract version versus build version":

> The path segment `/v1` is the contract; `info.version` is the build. A change that alters the contract in a breaking way opens `/v2` (§11); a change that only adds moves `info.version` forward

**Rule for the prototype: mount everything at `/v1`. The document's own version number, and the app build number, move independently and never appear in a path.**

### 1.1 Version policy, verbatim (§2.1)

> The major version is in the path. Additive changes (new optional fields, new endpoints, new enum values on response-only enums) ship without a bump. A breaking change (removed or renamed field, changed type, new required request field, changed status code semantics) ships as `/v2` served side by side with `/v1` for at least one release and at least 90 days; `/v1` responses then carry `Deprecation: true` and `Sunset: <HTTP-date>` headers and the OpenAPI operation is marked `deprecated: true`. Request-side enums are closed: an unknown value is 422. Response-side enums may grow; clients must treat unknown values as "other" and must not fail.

Two client obligations §11.2 makes explicit and calls enforced by the generated client:

> ignore unknown response fields, and never fail on an unknown response enum member. A client that pins `additionalProperties: false` on responses is misconfigured.

Breaking-change list (§11.3) that matters most for a prototype that may later become real: renaming an error `code`, moving a condition from 422 to 409, changing a default (`limit`, `show_inactive`), and changing a route's required permission in a more restrictive direction — all of these need `/v2`.

### 1.2 Hosts and time

| Item | Value |
|---|---|
| Production host | `https://debt.volt.co.th` |
| Staging host | `https://debt-stg.volt.co.th` (behind IAP for browsers; `/v1/webhooks/*` bypasses IAP) |
| Local development | `http://localhost:8000/v1` with `ALLOW_LOCAL_ADMIN=true` and the Identity Platform emulator |
| Time zone | RFC 3339 with explicit offset, normally `+07:00` (Asia/Bangkok). Dates are `YYYY-MM-DD` Gregorian. Buddhist-era years appear only inside generated PDFs, never in API responses. |

---

## 2. Auth model, as far as the API is concerned

### 2.1 The bearer token

- `Authorization: Bearer <ID token>` issued by **Identity Platform**, Google provider, project `volt-debt-prd` / `volt-debt-stg`. Verified RS256 against the Google secure-token JWKS.
- Claims checked: `iss = https://securetoken.google.com/<project_id>`, `aud = <project_id>`, `exp` future with 30 s leeway, `iat` not future, `auth_time` within the last **60 minutes** (server-side idle limit), `email_verified = true`, `firebase.sign_in_provider = google.com`, and the Google `hd` claim equals `volt.co.th`.
- Unknown email → `401 unauthenticated` with `extensions.reason = not_provisioned` (auto-provisioning allowed only for SALES_READONLY and MANAGEMENT_VIEWER). Inactive user → `401 session_revoked`.
- Session row keyed on token `jti`. CFG `max_concurrent_sessions` default 3, evicts oldest. Deactivating a user revokes all sessions and every subsequent request is 401 **within one request**.
- Two actions need a *fresh* second factor (`auth_time` within 5 minutes): personal-data export and erasure execution. Otherwise `403 export_mfa_required`.
- Break-glass `POST /v1/auth/local` exists in local and stg only; the route **404s in production** and the service refuses to start in prd with the flag set.

**No cookies for the API.** CORS is disabled in production because the API and the web app are same-origin behind one host; `http://localhost:5173` is allowed with credentials in local development only.

### 2.2 The principal — `GET /v1/me`

```json
{
  "uid": "018f3b1e-2c44-7e1a-8b3c-7a2f9d1c0e55",
  "email": "noon.k@volt.co.th",
  "display_name": "Noon",
  "roles": ["DEBT_OFFICER"],
  "permissions": {"col.contract.view": "OWN", "col.contact.log": "ALL", "col.ptp.create": "ALL"},
  "scope": {"contracts": "OWN", "team_uid": "018f...", "legal_entities": ["SPV"]},
  "officer_uid": "018f...",
  "locale": "th",
  "session": {"jti": "…", "expires_at": "2026-09-03T11:42:00+07:00", "auth_time": "2026-09-03T10:42:00+07:00"},
  "feature_flags": {"penalty_invoicing_enabled": true, "drive_mirror_enabled": true}
}
```

`feature_flags.penalty_invoicing_enabled` reads `true` above — superseded 2026-09-09, ruling 87;
this specimen showed `false` before the ruling turned invoicing on by default.

Scope values are `OWN` (officer's assigned customers), `TEAM` (supervisor's team), `ALL`.

### 2.3 Authorisation — the five router rules (§3.4, verbatim)

> (1) every `/v1` operation declares exactly one `x-permission`; (2) scope OWN, TEAM or ALL is applied as a query predicate, never as a post-filter; (3) a VIEW permission on a resource does not imply any ACTION on it; (4) an ACTION implies read of the specific record it acts on for the duration of the request only; (5) the same registry file generates `permissions.json` for the web client

The governing spec rule, quoted repeatedly through the document: **"Hiding a screen must also block its endpoint"** (Spec §21.2). Scope violations are answered `403 out_of_scope` on non-sensitive resources but **404 `not_found`** for documents, customers and contracts so existence is never leaked.

Permissions used by the screens in scope of this brief:

| Screen | Permission | Officer / Supervisor / Manager / Owner |
|---|---|---|
| Today List | `col.today_list.view` | OWN / TEAM / ALL / ALL |
| Contract card | `col.contract_card.view` | OWN / TEAM / ALL / ALL |
| Contract detail | `col.contract.view` | OWN / TEAM / ALL / ALL |
| Log a contact | `col.contact.log` | yes / yes / yes / yes |
| Override the daily lock | `col.contact.override` | **no / no / yes / yes** |
| Contact history | `col.contact.view_history` | OWN / TEAM / ALL / ALL |
| Create a PTP | `col.ptp.create` | yes / yes / yes / yes |
| Create a hold | `col.hold.create` | yes (PENALTY_SERVICE_HOLD via service issue only) / yes / yes / yes |
| Release a hold early | `col.hold.release_early` | no / no / yes / yes |
| Exception dashboard | `acc.exception_dashboard.view` | **no / no / yes / yes** plus ACCOUNTING, SYSTEM_ADMIN |
| Retry an exception | `acc.exception.retry` | no / no / yes / yes plus ACCOUNTING |
| Recovery board (read) | `mod.modification.view` | OWN / TEAM / ALL / ALL |
| Open / close a recovery path | `mod.recovery.open_path` / `mod.recovery.close_path` | no / no / yes / yes; LEGAL yes |
| Record a payment | `mny.transaction.record_payment` | **no / no / no / no** — ACCOUNTING only |
| Create a payment claim | `mny.claim.create` | yes / yes / yes / yes plus ACCOUNTING |
| Confirm a payment claim | `mny.claim.confirm` | **no / no / no / no** — ACCOUNTING only |

Note the two "no/no/no/no" rows: recording a payment and confirming a claim are **Accounting-role actions and are not available to the Debt Manager or the Owner**. That is deliberate (A-08, payment truth is PEAK).

---

## 3. Conventions every endpoint obeys

| Rule | Detail |
|---|---|
| Media type | `application/json; charset=utf-8`. Errors are `application/problem+json`. CSV exports go through signed URLs, never inline. |
| Field naming | `snake_case` for every JSON key and query parameter. Resource paths are **plural kebab-case nouns** (`/v1/payment-claims`). Custom actions use a **colon suffix** (`POST /v1/ptps/{uid}:renegotiate`), never a verb segment. |
| Identifiers | Every resource exposes `uid` (UUID v7) as its public identifier and path parameter. Human references (`contract_no`, `customer_no`, `document_no`, `handover_id`) are returned alongside and are searchable but are **never path parameters**. |
| Money | Strings with exactly two decimals, no thousands separator: `"5580.00"`. **Never floats.** Currency is THB everywhere and a `currency` field is not sent. |
| Rates | Strings as decimal fractions: `"0.079"` for 7.9 percent per year, `"0.0003"` for 0.03 percent per day (superseded 2026-09-09, ruling 87; was `"0.003"` for 0.3 percent per day). The client renders percentages. |
| Dates on money rows | Every transaction carries **both** `record_date` and `effective_date`. `effective_date` is the one used for the accounting period. |
| Legal entity | `legal_entity` is `EPC` or `SPV` on every money request and response. |
| Nulls | `null` means "no value". Absent keys are not sent in responses — all schema fields are always present. `dpd` is `null` while PRE_COLLECTION and `0` once collection has begun. |
| Booleans | JSON booleans, never `"Y"/"N"`. The spec's `amount_discussed_y_n` is the field `amount_discussed: boolean`. |
| Enums | Upper snake case. Dictionary codes are **at most 16 characters** and are returned as `{ "code": "...", "label_th": "...", "label_en": "..." }`. |
| Masking | `identity_no_masked` (e.g. `1-1234-5xxxx-xx-1`), `account_no_masked` (`xxx-x-xx123-4`), `phone_masked` in list responses. Full values only through reveal endpoints with a mandatory `reason` and an audit row. |
| Language | `Accept-Language: th` or `en` selects `title` and `detail`; **`message_th` is always present regardless.** Default `th`. |
| Body limit | 1 MiB for `/v1/*`; 64 KB for `/v1/webhooks/odoo`; 256 KB for `/v1/webhooks/peak/*`. Larger → 413 `payload_too_large`. |

Request identity headers:

| Header | Rule |
|---|---|
| `X-Request-Id` | Optional in (UUID or up to 64 chars of `A-Za-z0-9._-`); generated when absent and **always echoed**. It is the `instance` of every problem response as `urn:request:<id>`. |
| `traceparent` / `tracestate` | W3C Trace Context, continued by the service. |
| `X-Debt-Client` | `web/<version>`, `playwright/<run>`, `n8n`, `synthetic`. Used to **exclude synthetic traffic from KPI counts**. |

Caching and security: `Cache-Control: no-store` on every `/v1` response containing personal data (all except dictionaries, config metadata, call scripts, health and meta); `private, max-age=300` with `ETag` for dictionaries and scripts.

---

## 4. Pagination, filtering, sorting, field selection

Verbatim from §2.6:

| Aspect | Rule |
|---|---|
| Style | Cursor pagination on every list endpoint. **Offsets are not supported** (the Today List and ledger tables are large and change under the reader). |
| Query parameters | `limit` (default 50, maximum 200; KPI and audit endpoints maximum 500), `cursor` (opaque). |
| Response envelope | Three top-level members: `items`, a list of the resource; `page` carrying `next_cursor` (string or null), `has_more` (boolean) and `limit` (integer); and `meta` carrying `generated_at` and `total_estimate` (integer or null). `total_estimate` is present only when cheap (planner estimate) and is never exact. |
| Cursor encoding | base64url of a JSON tuple of the sort keys plus `uid`, signed with HMAC-SHA256 (APP_SESSION_KEY) and **bound to the principal and the filter hash**; a cursor reused with different filters or by another user is 422 `validation_failed` pointer `/cursor`. Cursors expire after 24 h. |
| Stable order | Every sort ends with `uid` as the tiebreaker so pages never overlap or skip. |
| Sorting | `sort=-dpd,contract_no` (leading minus for descending, comma-separated, **at most 3 keys**). Unknown keys are 422. |
| Filtering | Equality `status=ACTIVE`; set `status=ACTIVE,PAST_DUE` (IN); ranges `dpd_from=8&dpd_to=29`, `effective_date_from=…&effective_date_to=…`; booleans `is_active=true`; free text `q=` (name, contract_no, phone suffix, document_no; **never identity numbers in clear**); identity lookup only through `identity_no_hash`. |
| Scope filtering | Applied server-side from the principal's scope **before** any user filter; an Officer asking for another officer's customers gets an **empty page, not an error**. |
| Field selection | `fields=uid,contract_no,dpd` trims the response to the named top-level fields plus `uid`; used by the Today List grid. `expand=customer,officer` only where OpenAPI lists `x-expandable`. |
| Consistency | Lists read from the primary with `READ COMMITTED`; the card and ledger endpoints that must agree "to the satang" are computed in one transaction snapshot (`REPEATABLE READ`) per request. |

The literal envelope (§4.12):

```json
{
  "items": [],
  "page": { "next_cursor": "eyJkcGQiOjIyLCJ1aWQiOiIwMThmM2I5MSJ9", "has_more": true, "limit": 50 },
  "meta": { "generated_at": "2026-09-03T09:00:00+07:00", "total_estimate": 1234 }
}
```

Last page carries `"next_cursor": null` and `"has_more": false`.

### 4.1 Concurrency — ETag and If-Match

- Every **mutable** resource (customer channels, assignments, PTPs, holds, modifications, config values, dictionary items, templates, roles, users) returns `ETag: W/"<row_version>"` on GET and on every 2xx write.
- Immutable resources (transactions, ledger rows, audit rows, issued documents, **contact entries**) return a strong `ETag` of the content hash, for caching only.
- `If-Match` is **required** on PATCH, PUT, DELETE and on state-changing POST actions of mutable resources (`:approve`, `:reject`, `:release`, `:commit`). Missing → `428 precondition_required`. Mismatch → `412 optimistic_lock_conflict` with `extensions.current_etag` and `extensions.changed_fields`.
- `If-Match` is **not** required on: create (POST to a collection), append-only logs (contacts, attempts), reveal endpoints, job polling, all `/internal/*`.
- `row_version` also appears in the body as `version` for clients that cannot read headers.

### 4.2 Idempotency-Key

- `Idempotency-Key: <UUID v4>`, generated by the client **per user intent, not per retry**.
- Required on: every POST that creates a money row or triggers a PEAK call; **every POST that creates a contact entry**, PTP, arrangement, hold, assignment or handover commit; every document generation, export and upload intent; every webhook replay. Missing → `422 validation_failed` pointer `/headers/idempotency-key`.
- Scope is `(principal_uid, method, route template, key)`.
- Replay with the same body hash returns the stored response plus `Idempotency-Replayed: true` and `Idempotency-Original-Request-Id`. Same key + different body → `409 idempotency_key_reused`. Same key while still executing → `409 idempotency_in_progress` with `Retry-After: 2`.
- Client idempotency protects against double clicks. The **domain** keys (the contact daily lock, `(contract, ledger_date)`, the PEAK `idempotency_key`) protect against business duplicates and are enforced regardless of the header.

### 4.3 Asynchronous operations — 202 plus a job

Anything that can exceed roughly two seconds, calls a third party, renders a PDF or touches many rows returns **202 Accepted**, never 200 with a partial result and never 201 for the thing the job will create.

| Element | Rule |
|---|---|
| `Location` | `/v1/jobs/{job_uid}` — the canonical poll target |
| `Retry-After` | 3 for a posting retry, 5 for a document render, 10 for an export, 30 for a bulk import or reconcile run |
| Body | `JobAccepted`: `job_uid`, `kind`, `status`, `created_at`, `poll_url`, `subject`, `queue` |
| Validation | Every permission check, schema check and evaluable business rule runs **before** the 202. "A demand letter with a past deadline is 422, not a job that fails later." |
| Failure | A failed job is a **normal terminal state** with a problem-shaped `error` object, not an HTTP error on the poll. The poll answers 200 for every state. |

Job `status` enum: `QUEUED, RUNNING, SUCCEEDED, PARTIAL, FAILED, CANCELLED, EXPIRED`. Terminal jobs readable for 7 days, then 404. `GET /v1/jobs/{uid}` supports `If-None-Match` → 304. Poll backoff, verbatim: "1 s, 2 s, 3 s, 5 s, 8 s, then every 10 s to a ceiling of 5 minutes total for interactive jobs and 30 minutes for exports and imports."


---

## 5. Errors — RFC 9457 problem details

The document notes a deliberate deviation from the original brief:

> the brief asks for "RFC 7807 problem+json". RFC 7807 was obsoleted by RFC 9457 in 2023 with an identical media type and field set; this document and Project_Architecture_Blueprint.md §8.3 cite RFC 9457. Nothing a client does differs.

### 5.1 The envelope, verbatim (§2.4)

```json
{
  "type": "https://debt.volt.co.th/errors/contact_locked",
  "title": "Customer already contacted today",
  "status": 409,
  "detail": "A counting contact was logged for this customer today at 10:42 by Noon (result ANSWERED_AMOUNT_DISCUSSED). The Thai Debt Collection Act limit is one contact per customer per day.",
  "instance": "urn:request:018f3c2a-7b1e-7c9d-9f3a-2f1d0c4b5a61",
  "code": "contact_locked",
  "error_id": "DEBT-COL-0409",
  "message_th": "ลูกค้ารายนี้ถูกติดต่อแล้ววันนี้ เวลา 10:42 โดย นุ่น (ผลการติดต่อ: รับสายและแจ้งยอด) ตามกฎหมายติดตามทวงถามหนี้ติดต่อได้วันละ 1 ครั้ง",
  "retryable": false,
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "errors": [],
  "extensions": {
    "lock_level": "PERSON",
    "locked_by": {"uid": "018f...", "display_name": "Noon"},
    "locked_at": "2026-09-03T10:42:11+07:00",
    "result": "ANSWERED_AMOUNT_DISCUSSED",
    "override_allowed": false
  }
}
```

Field rules that are load-bearing:

- `code` — "Machine code, lower snake case, at most 40 chars. **The only field clients branch on.**"
- `error_id` — `DEBT-<MOD>-<HTTP status or 4-digit serial>`, for support tickets and test-case references.
- `message_th` — "Thai sentence for end users; **always present**."
- `retryable` — "True only for 429, 503 and 409 `optimistic_lock_conflict` after a refetch."
- `errors` — field errors `{ "pointer": "/promised_date", "code": "date_in_past", "message": "...", "message_th": "..." }`; **empty array** when not applicable, never absent.
- `extensions` — code-specific structured data; **empty object** when not applicable.
- `detail` is explicitly **outside the compatibility contract** (§11.1): "Clients that parse `detail` … are outside the contract and will break without notice."

### 5.2 HTTP status mapping, verbatim

> 400 malformed request (JSON, types); 401 unauthenticated or expired token; 403 authenticated but lacking the permission, or data outside scope when existence is not sensitive; 404 unknown `uid` within scope, and also used instead of 403 for documents, customers and contracts so existence is never leaked (Spec §21.2); 409 state conflicts (idempotency reuse, optimistic lock, contact lock, illegal lifecycle transition); 412 `If-Match` mismatch; 413 body too large; 415 wrong media type; 422 validation and business rules; 428 `If-Match` missing where required; 429 rate limited; 500 unexpected (reported to Error Reporting, never with detail); 502 upstream returned garbage; 503 dependency unavailable or circuit open; 504 upstream timeout.

### 5.3 THE TWO NAMED CODES THE REQUEST ASKED FOR DO NOT EXIST

I searched the entire repo, not only the five named files:

```
grep -rni "population_filter|population filter|closure_voids|voids_pending|voids pending" /Users/parattakorn/volt-debt-collection
→ zero matches
```

**`422 population_filter_unset` and `409 closure_voids_pending` appear nowhere in the local spec repo.** They are not in the §2.5 catalogue, not in the §9.1 per-module catalogue, not in §9.2 (the alias reconciliation table that records every earlier draft name), and not in the test cases, the PRD or the event contracts.

§9.2 is the specific place a renamed or aliased code would have been recorded. It exists and is complete, and it does not mention either name. Its closing line is:

> Owner of this reconciliation: Arina. Any request to rename a live code is a breaking change under §11 and needs a `/v2` plan, not a patch release.

**Do not invent these two codes in the prototype.** If the intent is real, the nearest existing semantics are:

| Asked-for name | Nearest real code in the spec | Why it is close, and how it differs |
|---|---|---|
| `422 population_filter_unset` | `422 feature_disabled` (`DEBT-CFG-0423`) — "Feature flag off"; and the KPI *null-with-banner* pattern for unset config: TC-KPI-008 returns `promise_kept_rate` as **null with `pending_confirmation: true`, `reason: ptp_kept_partial_weight_not_set`, `owner: Debt Manager`** rather than an HTTP error. | The spec's answer to "an indicator cannot be computed because a rule is unset" is a **200 with a null value and a banner**, not a 4xx. TC-KPI-008: "no default of 1.0 or 0.5 is assumed anywhere". If the prototype needs a 422 here, that is a **new** contract decision and must be recorded, not attributed to the spec. |
| `409 closure_voids_pending` | `409 recovery_path_closed` (`DEBT-MOD-0431`) — "Action on a closed path"; `409 illegal_transition` (`DEBT-MOD-0409`) with `extensions.from/to/allowed`; `409 posting_already_posted` (`DEBT-ACC-0409`). | The spec has no code for "closing this thing would void pending items". The closest *behaviour* is §17.2: rejecting a modification "discards the candidate schedule with an audit row … leaves no orphan"; and `POST /recovery-paths/{uid}:close` which requires a `reason_code` from `AGREEMENT_COMPLIED, REMOVAL_COMPLETE, ACCOUNT_CLOSED, OTHER` and states "**CLOSED (never deleted)**". |

### 5.4 The generic codes every endpoint can raise

Per §4: "Errors lists the codes specific to the operation **in addition to** the generic 400, 401, 403, 404, 422 `validation_failed`, 429."

| code | error_id | HTTP | When |
|---|---|---|---|
| `malformed_request` | DEBT-PLT-0400 | 400 | Body is not valid JSON or violates schema types |
| `unauthenticated` | DEBT-IAM-0401 | 401 | Missing, expired or invalid bearer token; `hd` not volt.co.th |
| `session_revoked` | DEBT-IAM-0402 | 401 | Session jti disabled |
| `forbidden` | DEBT-IAM-0403 | 403 | Permission missing |
| `out_of_scope` | DEBT-IAM-0404 | 403 | Permission held but record outside OWN/TEAM scope on a **non-sensitive** resource |
| `not_found` | DEBT-PLT-0404 | 404 | Unknown uid, **or sensitive record outside scope** |
| `idempotency_key_reused` | DEBT-PLT-0409 | 409 | Same key, different body hash within 24 h |
| `idempotency_in_progress` | DEBT-PLT-0410 | 409 | Same key, first request still executing |
| `optimistic_lock_conflict` | DEBT-PLT-0412 | 412 | If-Match ≠ current ETag |
| `precondition_required` | DEBT-PLT-0428 | 428 | If-Match missing on a mutable resource |
| `payload_too_large` | DEBT-PLT-0413 | 413 | — |
| `unsupported_media_type` | DEBT-PLT-0415 | 415 | — |
| `validation_failed` | DEBT-PLT-0422 | 422 | Field-level errors in `errors` |
| `rate_limited` | DEBT-PLT-0429 | 429 | Per-principal or per-route limit; `Retry-After` set |
| `dependency_unavailable` | DEBT-PLT-0503 | 503 | DB, Redis, KMS down or adapter circuit open; `extensions.dependency` |
| `upstream_timeout` | DEBT-PLT-0504 | 504 | Odoo, PEAK or Drive synchronous call timed out |
| `job_already_running` | DEBT-PLT-0409 | 409 | Manual job run while a run for the same business date is RUNNING |

### 5.5 COL codes — the collections board

| code | error_id | HTTP | When | `message_th` |
|---|---|---|---|---|
| `contact_locked` | DEBT-COL-0409 | **409** | Counting contact already logged today (Spec §8.4) | ลูกค้ารายนี้ถูกติดต่อแล้ววันนี้ |
| `contact_on_hold` | DEBT-COL-0422 | 422 | CONTACT_HOLD active (Spec §8.7, §16.5) | ลูกค้ารายนี้อยู่ระหว่างระงับการติดต่อ |
| `override_reason_required` | DEBT-COL-0423 | 422 | Manager override without `override_reason` | ต้องระบุเหตุผลในการยกเว้นการล็อก |
| `next_contact_required` | DEBT-COL-0424 | 422 | Result CALLBACK, PROMISE_TO_PAY or FOLLOW_UP without `scheduled_next_contact_at` | ต้องระบุวันนัดติดต่อครั้งถัดไป |
| `date_in_past` | DEBT-COL-0425 | 422 | `scheduled_next_contact_at` or `promised_date` before today | วันที่ต้องไม่เป็นอดีต |
| `stakeholder_type_required` | DEBT-COL-0426 | 422 | Missing `stakeholder_type` | ต้องระบุประเภทผู้ติดต่อ |
| `amount_discussed_required` | DEBT-COL-0427 | 422 | Outbound answered call without `amount_discussed` | ต้องระบุว่าได้แจ้งยอดหรือไม่ |
| `ptp_renegotiation_cap` | DEBT-COL-0428 | 422 | Third renegotiation of one instalment; case escalated to Manager | เกินจำนวนครั้งที่เลื่อนนัดได้ ส่งเรื่องถึงผู้จัดการแล้ว |
| `arrangement_replacement_reason_required` | DEBT-COL-0429 | 422 | New arrangement while a BROKEN one exists without `replaces_uid` and reason | ต้องอ้างอิงแผนเดิมที่ผิดนัดและระบุเหตุผล |
| `hold_reason_and_expiry_required` | DEBT-COL-0430 | 422 | Hold without reason code or expiry | การระงับต้องมีเหตุผลและวันหมดอายุ |
| `hold_release_authority` | DEBT-COL-0431 | **403** | Early release by a non-configured approver | ไม่มีสิทธิ์ยกเลิกการระงับก่อนกำหนด |
| `assignment_cap_exceeded` | DEBT-COL-0432 | 422 | Officer would exceed `customers_per_officer_cap` (default 100); Manager may pass `cap_override_reason` | จำนวนลูกค้าต่อพนักงานเกินกำหนด |
| `handover_preview_stale` | DEBT-COL-0433 | 409 | Commit of a bulk handover whose preview hash no longer matches | ตัวอย่างการโอนงานไม่ตรงกับข้อมูลปัจจุบัน กรุณาสร้างใหม่ |
| `handover_manual_items_pending` | DEBT-COL-0434 | 422 | Bulk handover includes a promise due within 7 days, a restructure in progress, a Legal case or a complaint not individually assigned | มีรายการที่ต้องมอบหมายรายบุคคลก่อนโอนงานแบบกลุ่ม |
| `today_list_not_ready` | DEBT-COL-0435 | **503** | Today List for the requested date has not been generated; `Retry-After` set; `extensions.last_run` | รายการติดตามประจำวันยังไม่พร้อม |

### 5.6 MNY codes — money and payments

| code | error_id | HTTP | When |
|---|---|---|---|
| `money_immutable` | DEBT-MNY-0405 | **405** | PATCH, PUT or DELETE on any money row — "Money is never edited or deleted" |
| `schedule_locked` | DEBT-MNY-0409 | 409 | Attempt to regenerate a schedule after origination |
| `reversal_target_already_reversed` | DEBT-MNY-0410 | 409 | Second reversal of the same entry |
| `allocation_rule_pending` | DEBT-MNY-0423 | 422 | Allocation requested while CFG `allocation_order.locked = false` |
| `closed_period` | DEBT-MNY-0424 | 422 | `effective_date` in a closed accounting period and no `closed_period_override` |
| `penalty_not_billable` | DEBT-MNY-0425 | 422 | Zero chargeable days, or under a PENALTY_SERVICE_HOLD |
| `waiver_authority_exceeded` | DEBT-MNY-0426 | **403** | Waiver above the approver's policy band |
| `waiver_first_occurrence_used` | DEBT-MNY-0427 | 422 | Supervisor waiver when one already exists in the rolling 12 months |
| `claim_requires_receipt` | DEBT-MNY-0428 | 422 | Accounting confirms a claim without a PEAK receipt reference (A-08) |
| `payment_method_card_data` | DEBT-MNY-0429 | 422 | Body contains card-like or credential data |
| `early_settlement_rule_pending` | DEBT-MNY-0430 | 422 | Settlement quote requested while Spec §6.8 is unconfirmed |
| `entity_unresolved` | DEBT-INT-0422 | 422 | Product group has no legal entity or the entity has no adapter — **EPC hits this at MVP** |
| `feature_disabled` | DEBT-CFG-0423 | 422 | Feature flag off — superseded 2026-09-09, ruling 87; was "penalty invoicing is OFF until CF1 closes". Invoicing is ON by default now; the flag stays Owner-tunable and this fires only when an Owner disables it |

### 5.7 ACC codes — the exception dashboard

| code | error_id | HTTP | When |
|---|---|---|---|
| `posting_not_retryable` | DEBT-ACC-0422 | 422 | Retry on VALIDATION or PERIOD_LOCKED without the permitted edit path |
| `posting_already_posted` | DEBT-ACC-0409 | 409 | Retry or withdraw on a POSTED row |
| `peak_reference_mismatch` | DEBT-ACC-0423 | 422 | "Close with PEAK reference" where the PEAK document's contact or amount differs |
| `adapter_write_forbidden` | DEBT-ACC-0403 | 403 | Any attempt to post a REGULAR invoice or receipt through Debt (D-05) |
| `posting_failed` | — | **200** | Not an HTTP error: a terminal posting outcome carried on a job's `error` object and on `evt.accounting.posting_status_changed` |

### 5.8 MOD codes — the recovery board

| code | error_id | HTTP | When |
|---|---|---|---|
| `illegal_transition` | DEBT-MOD-0409 | 409 | Lifecycle transition not in the matrix; `extensions.from`, `extensions.to`, `extensions.allowed` |
| `approval_authority` | DEBT-MOD-0403 | 403 | Approver lacks the route step **as at the approval date** |
| `approval_ratify_after_forbidden` | DEBT-MOD-0423 | 422 | Approval dated after the effective date for write-off — "Acting first and ratifying afterwards is not permitted" |
| `modification_payload_invalid` | DEBT-MOD-0422 | 422 | "a modification without a payload is invalid" |
| `entry_gate_unpaid` | DEBT-MOD-0424 | 422 | Restructure submit before the 40 percent upfront is recorded |
| `restructure_cap_reached` | DEBT-MOD-0425 | 422 | Third restructure, or arrangement-plus-restructure over the cap of two, without Owner exception |
| `candidate_schedule_missing` | DEBT-MOD-0426 | 422 | Approval attempted before a candidate schedule exists |
| `acknowledgement_missing` | DEBT-MOD-0427 | 422 | Restructure activation before the signed acknowledgement is stored |
| `npl_auto_flag_forbidden` | DEBT-MOD-0428 | 422 | NPL flag without a completed **manual** assessment |
| `npl_excluded_service_issue` | DEBT-MOD-0429 | 422 | NPL flag while a service-issue hold or restructure is in progress |
| `collateral_required` | DEBT-MOD-0430 | 422 | Path C or D opened, or repossession, without a resolved collateral row |
| `recovery_path_closed` | DEBT-MOD-0431 | 409 | Action on a closed path |
| `cancellation_scope` | DEBT-MOD-0432 | 422 | Cancellation requested for a contract not yet activated |

### 5.9 Codes that carry structured `extensions` (§9.3)

The client renders from `extensions`, not from `detail`, because the values drive the next action.

| code | `extensions` keys | What the client does |
|---|---|---|
| `contact_locked` | `lock_level, locked_by, locked_at, result, contact_uid, unlocks_at, override_allowed, override_permission` | Show who contacted and when; offer the override button **only when `override_allowed` and the user holds `override_permission`** |
| `optimistic_lock_conflict` | `current_etag, changed_fields, changed_by, changed_at` | Refetch, show a conflict banner naming the fields that moved |
| `idempotency_in_progress` | `original_request_id, started_at` | Wait `Retry-After` and poll rather than resubmitting |
| `rate_limited` | `bucket, limit, reset_at` | Disable the control until `reset_at` |
| `validation_failed` | none — the `errors` array carries `pointer, code, message, message_th` | Attach each error to its form field by JSON pointer |
| `today_list_not_ready` | `last_run, expected_by, business_date` | Show the waiting state and the expected time; `Retry-After` drives the retry |
| `assignment_cap_exceeded` | `current_count, cap, override_permission` | Offer the Manager override with a reason |
| `handover_preview_stale` | `preview_hash, generated_at` | Regenerate the preview |
| `handover_manual_items_pending` | `items` | List the cases needing individual assignment |
| `illegal_transition` | `from, to, allowed` | Name the states, as Spec §18.5 requires a rejection to do |
| `posting_not_retryable` | `error_class, permitted_actions` | Show redate, close-with-reference or withdraw instead of retry |
| `posting_failed` | `error_class, res_code, res_desc, attempt, exception_uid, correction_due_by` | Open the exception; `correction_due_by` is the one-business-day window |
| `closed_period` | `closed_through_date, legal_entity, allowed_actions` | Offer redate or an unlock request |
| `entity_unresolved` | `product_group_uid, company_id, adapter` | Point Accounting at the missing mapping |
| `feature_disabled` | `flag, owner, expected_decision` | Name the flag and who is deciding |
| `precollection_incomplete` | `missing, owner_role` | List the outstanding items and who owns them |
| `dependency_unavailable` | `dependency, circuit_state, since` | Name the system that is down |

### 5.10 Alias table (§9.2) — names that are NOT emitted

Left column never appears on the wire; right column does.

| Name used elsewhere | Code emitted by the API |
|---|---|
| `contact_limit_reached` | **`contact_locked`** |
| `restructure_gate_not_met` | **`entry_gate_unpaid`** |
| `period_locked` | **`closed_period`** (PERIOD_LOCKED is the PEAK error *class*, not an API code — both exist and mean different things) |
| `permission_denied` | **`forbidden`** |
| `role_exceeds_creator` | **`custom_role_exceeds_creator`** |


---

## 6. Endpoint catalogue, by screen

All paths are under `/v1`. `IK` = `Idempotency-Key` required. `IM` = `If-Match` required. Every list endpoint supports the §4 paging rules. The Errors column lists **operation-specific** codes only — the generic set of §5.4 always applies on top.

### 6.1 Today list / work queue (COL)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/today-list` | `col.today_list.view` | query `date` (default today Bangkok), `officer_uid` (Supervisor or Manager only), `priority` (1–6), `sort` (`priority` default, `risk_score`, `oldest_dpd`), `include_completed` | `TodayList`: `run` (generated_at, run_uid), groups **grouped by customer never by contract**, each with priority, reason, contracts, aggregate overdue, oldest dpd, risk band, contact_lock state, last contact, upcoming flag | `today_list_not_ready` (503) |
| GET | `/today-list/items/{uid}` | `col.today_list.view` | none | `TodayListItem` with **full** contact and operations history — "not only the most recent entry" | — |
| POST | `/today-list/items/{uid}:complete` | `col.task.complete` | IK, IM; `{ "outcome_code": "...", "note": "..." }` | `TodayListItem` COMPLETED | — |
| GET | `/today-list/runs` | `plt.jobs.view` or `col.today_list.view` (Manager) | Filters: `from`, `to` | Page of `TodayListRun` (started, finished, counts by priority, status) | — |
| GET | `/customers/{uid}/today-list` | `col.today_list.view` | none | `TodayListCustomerGroup` for that customer | `today_list_not_ready` |
| GET | `/officers/{uid}/workload` | `col.assignment.view` | none | `Workload` (customers, cap from `customers_per_officer_cap`, overdue count, promises due next 7 days) | — |
| GET | `/tasks` | `col.task.view` | Filters: `kind` (`BROKEN_PROMISE, CLAIM_REJECTED, HOLD_EXPIRED, RESTRUCTURE_REQUEST, PAYMENT_METHOD_CLOSED, EXCEPTION, MANAGER_ESCALATION, PRECOLLECTION_MISSING`), `status`, `assignee_uid`, `due_from`, `due_to` | Page of `Task` (preloaded context) | — |
| POST | `/tasks/{uid}:complete` | `col.task.complete` | IK, IM; `{ "outcome": "...", "note": "..." }` | `Task` DONE | — |
| POST | `/tasks/{uid}:reassign` | `col.assignment.assign` | IK, IM; `{ "assignee_uid": "...", "reason": "..." }` | `Task` | — |

**The concrete Today List response** — this is the shape to build against (§5.8), abridged:

```json
{
  "run": {
    "run_uid": "018f3c10-0d00-7a00-8000-0102030405f0",
    "business_date": "2026-09-03",
    "generated_at": "2026-09-03T02:31:07+07:00",
    "job": "today-list"
  },
  "items": [
    {
      "uid": "018f3c11-1a00-7b00-8100-0102030405f1",
      "priority": 1,
      "reason_code": "BROKEN_PROMISE",
      "customer": {
        "uid": "018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12",
        "customer_no": "C-000871",
        "display_name": "สมชาย ใจดี",
        "phone_masked": "08x-xxx-4471",
        "contract_count": 2
      },
      "aggregate_overdue": "17856.00",
      "oldest_dpd": 33,
      "contact_lock": {"state": "OPEN", "locked_by": null, "unlocks_at": null}
    },
    {
      "uid": "018f3c11-2b00-7b00-8200-0102030405f2",
      "priority": 2,
      "reason_code": "PROMISE_DUE_TODAY",
      "customer": { "…": "…" },
      "aggregate_overdue": "5580.00",
      "oldest_dpd": 4,
      "contact_lock": {
        "state": "LOCKED",
        "locked_by": {"uid": "018f3b1e-…", "display_name": "Noon"},
        "unlocks_at": "2026-09-04T00:00:00+07:00"
      }
    }
  ],
  "page": { "next_cursor": "eyJwIjoyLCJkIjo0…", "has_more": true, "limit": 2 },
  "meta": {
    "generated_at": "2026-09-03T08:04:19+07:00",
    "total_estimate": 47,
    "counts_by_priority": {"1": 6, "2": 9, "3": 12, "4": 8, "5": 7, "6": 5}
  }
}
```

Note `meta.counts_by_priority` — an extra `meta` member beyond the standard envelope, specific to this endpoint.

Cursor rule for this endpoint, verbatim: "Changing `date`, `officer_uid`, `priority` or `sort` while replaying a cursor is 422 `validation_failed` with pointer `/cursor`, and a cursor older than 24 hours or belonging to another principal is rejected the same way."

Field selection is used here: `GET /v1/today-list?date=…&limit=2&sort=priority,-dpd&fields=uid,priority,reason_code,customer,aggregate_overdue,oldest_dpd,contact_lock`.

### 6.2 Contract detail and the summary card (INT + MNY)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/contracts` | `col.contract.view` | Filters: `status` (lifecycle), `payment_type`, `legal_entity`, `officer_uid`, `customer_uid`, `dpd_from`, `dpd_to`, `aging_bucket`, `product_group_uid`, `activated_from`, `activated_to`, `has_open_exception`, `q`. Sort: `dpd`, `contract_no`, `activated_at`, `remaining_balance` | Page of `ContractSummary` | — |
| GET | `/contracts/{uid}` | `col.contract.view` | `expand=customer,officer,schedule_summary,holds,open_exception` | `Contract`; `dpd` **null while PRE_COLLECTION**; `precollection_checks` array with the eight Spec §24.2 items and their status | — |
| **GET** | **`/contracts/{uid}/card`** | `col.contract_card.view` | none | `ContractCard`: **all six card sections plus the arrears block in priority order, computed server-side in one snapshot**; `penalty.indicative` boolean; `unconfirmed` flag and banner text when an open posting exception exists; `contact_lock` state | — |
| GET | `/contracts/{uid}/arrears` | `col.contract_card.view` | query `as_of` | `ArrearsBlock` in Spec §10.3 order: `total_arrears_payable_today`, `dpd` and bucket, `accrued_penalty` with composition, `next_due_date`, `next_instalment_amount`, `full_payoff`; `basis_ledger_date` | — |
| GET | `/contracts/{uid}/status-history` | `col.contract.view` | none | List of `LifecycleTransition` (from, to, actor, record_date, effective_date, reason, modification_uid) | — |
| GET | `/contracts/{uid}/schedule` | `mny.schedule.view` | query `version` (default current), `as_of` | `RepaymentSchedule`: header (principal_amount, annual_interest_rate, term_months, total_interest, total_amount, installment_amount, first_due_date, final_instalment_amount as the balancing figure) and rows in four column groups Disbursement / Expected / Paid / Scheduled, each split principal, interest, fee; `status` per row; `superseded_by_version` when archived | — |
| GET | `/contracts/{uid}/instalments` | `mny.schedule.view` | Filters: `status` (`SCHEDULED, DUE, PARTIALLY_PAID, PAID, OVERDUE, WAIVED, SUPERSEDED`) | Page of `Instalment` | — |
| GET | `/contracts/{uid}/ledger` | `mny.ledger.view` | Filters `from`, `to` (default last 90 days); **limit up to 366** | Page of `LedgerDay`: `opening_balance, payments_received, interest_for_day, penalty_for_day, closing_balance, cumulative_arrears, principal_outstanding, service_issue_frozen, penalty_accrued_today, dpd_on_date` (null or integer) | — |
| GET | `/contracts/{uid}/transactions` | `mny.transaction.view` | Filters: `txn_type`, `posting_status`, `bucket`, `show_inactive` (**default false** hides reversed pairs), `effective_date_from`, `effective_date_to` | Page of `Transaction` (record_date, effective_date, legal_entity, txn_type, amount, allocation buckets, `posting_status` ∈ `PENDING POSTED FAILED VOIDED NOT_APPLICABLE`, external_ref, reversal_of_uid) | — |
| GET | `/contracts/{uid}/penalties` | `mny.penalty.view` | Filters: `status` (`ACCRUED_UNBILLED, NEGOTIATED, BILLED, PAID, WAIVED, REJECTED`) | Page of `Penalty` with `chargeable_days`, `daily_rate`, `rate_resolution_level`, `indicative` | — |
| GET | `/customers/{uid}` | `int.customer.view` | `expand=contracts,channels,blacklist,officer` | `Customer` (multi-contract aggregate view) | — |
| POST | `/customers/{uid}:reveal` | `int.customer.reveal_identity` | `{ "field": "identity_no" \| "phone" \| "email", "reason": "..." }` | `{ "field": "identity_no", "value": "1123456789012", "revealed_at": "...", "log_uid": "..." }` | `access_reason_required`, `rate_limited` |

The card contract, verbatim from §4.1: "**Every figure is computed server-side and returned by one endpoint; the interface performs no arithmetic**". The arrears rule, from REQ-COL-027 and TC-COL-052: fields must come back in the stated order, and "a response that leads with the next instalment fails the test."

Card sections (REQ-COL-026), six of them: 1 contract information; 2 payment status; 3 penalty and promise tracking (accrued unbilled, billed, paid, waived penalty — **four separate figures, never netted into one**, plus broken promise count, active promises, partially kept count); 4 multi-contract view (aggregate overdue, total penalty accrued, oldest DPD, "mark as contacted applies to all"); 5 status; 6 quick actions (Call, LINE, log contact, create promise, flag service issue, submit restructure, download schedule).

### 6.3 Contact logging (COL) — the daily-lock-guarded log

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| **POST** | **`/contacts`** | `col.contact.log` | IK; body `ContactCreate` | **201** `Contact` with `counted: true\|false`, `lock_consumed`, `override: false` | `contact_locked` (409), `contact_on_hold`, `override_reason_required`, `next_contact_required`, `date_in_past`, `stakeholder_type_required`, `amount_discussed_required` |
| GET | `/contacts` | `col.contact.view_history` | Filters: `customer_uid`, `contract_uid`, `officer_uid`, `direction`, `channel`, `result_code`, `counted`, `from`, `to` | Page of `Contact` | — |
| GET | `/contacts/{uid}` | `col.contact.view_history` | none | `Contact` | — |
| PATCH | `/contacts/{uid}/next-contact` | `col.contact.log` | IM; `{ "scheduled_next_contact_at": "..." \| null, "reason": "..." }` — clearing removes the case from Priority 3 and is audited **under cleared fields** | `Contact` | `date_in_past` |
| POST | `/customers/{uid}/contacts:mark-contacted` | `col.contact.log` | IK; `ContactCreate` **without** `contract_uid` | 201 `Contact` applied to **all** the customer's contracts at once | as `POST /contacts` |
| **GET** | **`/customers/{uid}/contact-lock`** | `col.contact.log` | query `on_date` (default today Bangkok) | `ContactLockState`: `state` ∈ `OPEN \| LOCKED \| ON_HOLD`, `locked_by`, `locked_at`, `result`, `unlocks_at`, `override_allowed` | — |
| GET | `/reminders` | `col.reminder.view` | Filters: `customer_uid`, `contract_uid`, `touch` (`T-7, T-3, T-0, T+3, T+7, T+10, T+13`), `channel`, `status` (`QUEUED, SENT, DELIVERED, READ, FAILED, BLOCKED, SUPPRESSED`), `from`, `to` | Page of `Reminder` (template_uid, version, channel, recipient masked, render_result, delivery timestamps) | — |
| POST | `/contracts/{uid}/reminders:suppress` | `col.reminder.suppress` | IK; `{ "until": "...", "reason_code": "..." }` | `ReminderSuppression` | — |
| GET | `/call-scripts` | `col.call_script.view` | query `scenario` (`FIRST_CONTACT, BROKEN_PROMISE, PRE_LEGAL, DECEASED_ESTATE`), `contract_uid` | `CallScriptRendered` (active version only; **display-only, never sent**; unknown data shows the inline marker ยังไม่มีข้อมูล) | — |

**`ContactCreate` request body, verbatim from the §5.2 worked example:**

```json
{
  "customer_uid": "018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12",
  "contract_uid": "018f3b92-1d33-7b4f-8e62-7c8d9f0a1b23",
  "direction": "OUTBOUND",
  "channel": "PHONE",
  "stakeholder_type": "BORROWER",
  "result_code": "ANSWERED_NO_COMMITMENT",
  "amount_discussed": true,
  "note": "โทรติดตามยอดค้างงวดกันยายน",
  "occurred_at": "2026-09-03T14:05:11+07:00"
}
```

Headers on that call: `Authorization`, `Content-Type`, `Idempotency-Key`, `Accept-Language: th`, `X-Debt-Client: web/1.4.2`, `X-Request-Id`.

**The 409 refusal writes nothing** (§5.2, verbatim):

> Nothing is written: a refused contact never creates a row, so the daily count cannot drift. The refusal itself is audited under feature `col.contact.log` with outcome BLOCKED, which is what the compliance report counts.

Two variations the client must handle, verbatim:

> A Manager repeating the same body with `"override_reason": "ลูกค้าโทรกลับและขอให้ติดต่อซ้ำ"` and permission `col.contact.override` receives 201 with `"override": true` and an alert to the Debt Manager. An officer logging a NOTIFICATION-category touch (a reminder, Spec §9.1) is never blocked, because reminders are not contacts; that path is §8, not this endpoint.

### 6.4 Promises to pay and arrangements (COL)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/ptps` | `col.contract.view` | Filters: `status` (`CREATED, ACTIVE, KEPT, PARTIALLY_KEPT, BROKEN, RENEGOTIATED`), `customer_uid`, `contract_uid`, `officer_uid`, `promised_date_from`, `promised_date_to` | Page of `Ptp` | — |
| POST | `/contracts/{uid}/ptps` | `col.ptp.create` | IK; `{ "promised_amount": "...", "promised_date": "...", "linked_instalment_uid": "...", "contact_uid": "...", "send_confirmation": true }` | 201 `Ptp` ACTIVE with a **durable timer** scheduled; optional PTP_CONFIRMATION document job | `date_in_past` |
| GET | `/ptps/{uid}` | `col.contract.view` | none | `Ptp` with evaluation (classified **from allocation**) | — |
| POST | `/ptps/{uid}:renegotiate` | `col.ptp.renegotiate` | IK, IM; `{ "promised_amount": "...", "promised_date": "...", "reason": "..." }` | 201 new `Ptp`, original RENEGOTIATED, `renegotiation_count` | `ptp_renegotiation_cap` (third → Manager task) |
| POST | `/ptps/{uid}:cancel` | `col.ptp.create` | IK, IM; `{ "reason": "..." }` | `Ptp` CANCELLED (**only before the promised date**) | `illegal_transition` |
| GET | `/arrangements` | `col.contract.view` | Filters: `status` (`ACTIVE, COMPLETED, BROKEN, CANCELLED`), `customer_uid` | Page of `Arrangement` (header with `paid_n_of_m`) | — |
| POST | `/contracts/{uid}/arrangements` | `col.arrangement.create` | IK; `total_amount`, `children[]`, `replaces_uid`, `replacement_reason` | 201 `Arrangement` with child `Ptp`s | `arrangement_replacement_reason_required`, `restructure_cap_reached` |
| POST | `/arrangements/{uid}:acknowledge` | `col.arrangement.acknowledge` | IK, IM | `Arrangement` | — |
| POST | `/arrangements/{uid}:cancel` | `col.arrangement.create` | IK, IM; `{ "reason": "..." }` | `Arrangement` CANCELLED | — |

`POST /contracts/{uid}/ptps` **201 response, verbatim** (§5.3):

```json
{
  "uid": "018f3c2c-4d61-7a10-9b22-5c6d7e8f9a01",
  "contract_uid": "018f3b92-1d33-7b4f-8e62-7c8d9f0a1b23",
  "customer_uid": "018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12",
  "status": "ACTIVE",
  "promised_amount": "5580.00",
  "promised_date": "2026-09-10",
  "linked_instalment_uid": "018f3b93-2e44-7c50-9f73-8d9e0a1b2c34",
  "created_from_contact_uid": "018f3c1f-0a5b-7d2e-8c44-1b3e5f7a9c02",
  "renegotiation_count": 0,
  "counts_toward_restructure_cap": false,
  "evaluation": {"evaluate_at": "2026-09-11T02:15:00+07:00", "job": "ptp-autocheck"},
  "confirmation_document": {
    "job_uid": "018f3c2c-5e70-7b20-8c33-6d7e8f9a0b12",
    "status": "QUEUED",
    "type": "PTP_CONFIRMATION"
  },
  "record_date": "2026-09-03",
  "effective_date": "2026-09-03",
  "legal_entity": "SPV",
  "version": 1
}
```

Response headers on that 201: `Location: /v1/ptps/{uid}`, `ETag: W/"1"`, `Cache-Control: no-store`.

The arrangement body (§4.12):

```json
{
  "total_amount": "15000.00",
  "children": [
    { "promised_amount": "3000.00", "promised_date": "2026-09-10" },
    { "promised_amount": "6000.00", "promised_date": "2026-09-25" },
    { "promised_amount": "6000.00", "promised_date": "2026-10-10" }
  ],
  "replaces_uid": null,
  "replacement_reason": null
}
```

### 6.5 Holds and service issues (COL)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/holds` | `col.contract.view` | Filters: `hold_type` (`CONTACT_HOLD, LEGAL_HOLD, PENALTY_SERVICE_HOLD`), `status` (`ACTIVE, EXPIRED, RELEASED`), `customer_uid`, `contract_uid` | Page of `Hold` (reason code, approver, start, expiry, released_by) | — |
| POST | `/contracts/{uid}/holds` | `col.hold.create` | IK; `{ "hold_type": "...", "reason_code": "...", "starts_on": "...", "expires_on": "...", "approver_uid": "...", "detail": "..." }` — **all four of reason, approver, start, expiry are mandatory** | 201 `Hold`; PENALTY_SERVICE_HOLD freezes DPD and penalty from `starts_on` | `hold_reason_and_expiry_required` |
| POST | `/holds/{uid}:release` | `col.hold.release_early` | IK, IM; `{ "reason": "..." }` | `Hold` RELEASED; **officer notified** | `hold_release_authority` (403) |
| POST | `/contracts/{uid}/service-issues` | `col.service_issue.flag` | IK; `{ "complaint": "...", "contact_uid": "...", "installation_report_url": "..." }` | 201 `ServiceIssue` with an **auto-created PENALTY_SERVICE_HOLD** and an OPS Maintenance ticket request event; `ticket_ref` null until acknowledged | — |
| POST | `/service-issues/{uid}:resolve` | `col.service_issue.flag` | IK, IM; `resolution_date`, `resolution_summary`, `dpd_reset_mode` (`CONTINUE_FROM_FROZEN \| PARTIAL \| FULL`), `evidence_upload_uids[]` | `ServiceIssue` RESOLVED and a `DpdReset` | `approval_authority` (**FULL needs Supervisor or Manager**) |
| POST | `/service-issues/{uid}:mark-unresolvable` | `col.service_issue.flag` | IK, IM; `{ "reason": "..." }` | `ServiceIssue` UNRESOLVABLE; Manager task | — |
| GET | `/service-issues/audit-samples` | `col.service_issue.audit` | query `month`, `officer_uid` | **10 percent random sample per officer per month**, each with `reviewed`, `finding` | — |
| POST | `/service-issues/audit-samples/{uid}:review` | `col.service_issue.audit` | IK, IM; `{ "finding": "OK" \| "ABUSE_SUSPECTED", "note": "..." }` | `AuditSample` | — |
| POST | `/contracts/{uid}/dpd-resets` | `mny.dpd.reset_partial` or `mny.dpd.reset_full` | IK; `mode`, `resume_from_date`, `evidence_upload_uids[]`, `hold_uid`, `reason` | 201 `DpdReset` (before, after, approver) | `validation_failed` (evidence missing), `approval_authority` |

`POST /contracts/{uid}/dpd-resets` body (§4.12):

```json
{
  "mode": "PARTIAL",
  "resume_from_date": "2026-10-11",
  "evidence_upload_uids": ["018f4a10-0000-7000-8000-000000000001"],
  "hold_uid": "018f4a11-0000-7000-8000-000000000002",
  "reason": "Inverter replaced, service issue closed"
}
```

**The three hold types are not interchangeable** (TC-COL-063, verbatim):

> CONTACT_HOLD stops outbound contact on every channel through one server-side guard while DPD and penalty continue; LEGAL_HOLD records a legal position and does not stop contact, so a call the same day is still permitted; PENALTY_SERVICE_HOLD suspends penalty accrual and DPD counting while contact may continue; **no endpoint, flag or field stops everything at once**, and `hold_types` is LOCKED policy

DPD reset authority (TC-COL-067): *continue from frozen* is an Officer action; *partial reset* is an Officer action **but 422s without evidence attached**; *full reset* requires Supervisor or Manager and returns **403 `approval_authority`** for an Officer.

Expiry behaviour (TC-COL-070): at expiry the hold becomes EXPIRED **without human action**, `expired_notified_at` is set, the officer is notified, and contact and reminders resume the same day. "A hold is never simply deleted, so a freeze can no longer be applied and forgotten."

### 6.6 Payments (MNY) — claims, transactions, methods

**The governing rule (A-08): payment truth is PEAK.** A bank-slip upload creates a `payment-claim` in PENDING; only ACCOUNTING confirms it; confirmation requires a PEAK receipt reference; **DPD is never reset by a claim.**

Money rows are append-only: **PATCH, PUT and DELETE on any path in this section return 405 `money_immutable`. Corrections are reversals.**

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/payment-claims` | `mny.claim.view` | Filters: `status` (`PENDING, CONFIRMED, REJECTED, EXPIRED`), `contract_uid`, `officer_uid`, `age_hours_from` | Page of `PaymentClaim` | — |
| POST | `/contracts/{uid}/payment-claims` | `mny.claim.create` | IK; `{ "claimed_amount": "...", "value_date": "...", "channel": "TRANSFER" \| "QR" \| "CASH", "slip_upload_uid": "...", "note": "..." }` | 201 `PaymentClaim` PENDING — **never resets DPD; card shows "claimed, unconfirmed"** | `upload_rejected` (slip not CLEAN) |
| POST | `/payment-claims/{uid}:confirm` | `mny.claim.confirm` (**ACCOUNTING only**) | IK, IM; `{ "peak_receipt_ref": "R-...", "confirmed_amount": "...", "effective_date": "..." }` | `PaymentClaim` CONFIRMED and the linked `Transaction` | `claim_requires_receipt` |
| POST | `/payment-claims/{uid}:reject` | `mny.claim.confirm` | IK, IM; `{ "reason_code": "...", "detail": "..." }` | `PaymentClaim` REJECTED; **officer task created** | — |
| POST | `/contracts/{uid}/transactions` | `mny.transaction.record_payment` (**ACCOUNTING only**) | IK; `{ "txn_type": "PAYMENT", "amount": "6000.00", "effective_date": "2026-09-03", "legal_entity": "SPV", "source": "PEAK_RECEIPT", "external_ref": "R-2026-000123", "payment_method_uid": "...", "note": "..." }` — manual recording only; the normal path is the PEAK webhook | 201 `Transaction` with `Allocation` rows (**oldest instalment first, then the configured component order**) | `closed_period`, `allocation_rule_pending`, `entity_unresolved` |
| POST | `/transactions/{uid}:reverse` | `mny.transaction.reverse` | IK; `{ "reason": "...", "effective_date": "..." }` | 201 `Transaction` (mirror entry, `reversal_of_uid`) and the void posting if the original was POSTED | `reversal_target_already_reversed`, `closed_period` |
| POST | `/contracts/{uid}/adjustments` | `mny.adjustment.create` | IK; `{ "amount": "...", "bucket": "FEE", "direction": "DEBIT" \| "CREDIT", "effective_date": "...", "legal_entity": "SPV", "reason_code": "...", "post_to_accounting": true }` | 201 `Transaction` | `closed_period`, `entity_unresolved` |
| GET | `/contracts/{uid}/allocations` | `mny.transaction.view` | Filters: `instalment_uid`, `transaction_uid` | Page of `Allocation` — **six figures: principal, interest, fee, each current and overdue** | — |
| GET | `/contracts/{uid}/payment-methods` | `mny.payment_method.view` | none | List of `PaymentMethod` (type, bank, holder_name, `account_no_masked`, is_primary, active_from, active_to, verified_at, failures) | — |
| POST | `/contracts/{uid}/payment-methods` | `mny.payment_method.manage` | IK; `{ "type": "DIRECT_DEBIT" \| "TRANSFER" \| "CASH" \| "OTHER", "bank_code": "...", "holder_name": "...", "account_no": "...", "active_from": "..." }` | 201 `PaymentMethod` (account number encrypted, masked in response) | `payment_method_card_data` |
| POST | `/payment-methods/{uid}:set-primary` | `mny.payment_method.manage` | IK, IM; `{ "reason": "...", "effective_date": "..." }` | `PaymentMethod`; **the previous primary gets `active_to` — it closes rather than being overwritten** | — |
| POST | `/payment-methods/{uid}/failures` | `mny.payment_method.manage` | IK; `{ "reason_code": "INSUFFICIENT_FUNDS" \| "ACCOUNT_CLOSED" \| "INCORRECT_DETAILS", "occurred_on": "..." }` | 201 `PaymentMethodFailure`; **ACCOUNT_CLOSED flags the method and creates a task instead of incrementing DPD** | — |
| POST | `/payment-methods/{uid}:reveal` | `mny.payment_method.reveal` | `{ "reason": "..." }` | `{ "account_no": "...", "log_uid": "..." }` | `access_reason_required` |
| GET | `/payment-methods/exceptions` | `acc.exception_dashboard.view` | none | Page of contracts with **no active method** | — |
| POST | `/penalties/{uid}:bill` | `mny.penalty_bill.approve` | IK, IM; `{ "effective_date": "...", "legal_entity": "SPV" }` | **202 Job** → `Transaction` PENALTY_INVOICE PENDING then POSTED | `feature_disabled` (**superseded 2026-09-09, ruling 87** — invoicing is ON by default; fires only if an Owner disables the Owner-tunable flag; was "until CF1 closes — penalty invoicing is OFF"), `penalty_not_billable`, `closed_period` |
| POST | `/penalties/{uid}/waivers` | `mny.penalty.waive_small` / `_large` / `_above_policy` (router picks by band) | IK; `{ "waived_amount": "...", "reason_code": "...", "detail": "..." }` | 201 `Modification` of type PENALTY_WAIVER — **"A waiver is a modification type, never a direct edit"** | `waiver_authority_exceeded`, `waiver_first_occurrence_used` |
| POST | `/uploads/intents` | `doc.upload.create` | IK; `{ "purpose": "PAYMENT_SLIP" \| …, "filename": "slip.jpg", "declared_mime": "image/jpeg", "byte_size": 812344, "contract_uid": "...", "customer_uid": "..." }` | 201 `UploadIntent`: `upload_uid`, `put_url` (GCS V4 signed PUT to `uploads-quarantine`, **TTL 300 s**, `content-length-range` max 26,214,400), `required_headers`, `expires_at`, `status: PENDING_UPLOAD` | `upload_type_not_allowed`, `upload_too_large`, `uploads_paused` |
| GET | `/uploads/{uid}` | `doc.upload.view` | none | `Upload`: `status` ∈ `PENDING_UPLOAD, UPLOADED, SCANNING, CLEAN, REJECTED, EXPIRED`; `rejection_reason` only `TYPE_NOT_ALLOWED, MAGIC_MISMATCH, TOO_LARGE, ARCHIVE, POLYGLOT, SCAN_ERROR, REJECTED` — **INFECTED is never named to the uploader** | — |

The upload flow matters for payments because a claim requires a CLEAN slip: **the API never receives file bytes** (D-06/D-07). Client PUTs directly to the signed URL, then optionally calls `POST /uploads/{uid}:complete` with `{ "sha256": "..." }` — "the Eventarc finalize event is authoritative and this call merely shortens the wait."

### 6.7 Exception dashboard (ACC)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| **GET** | **`/accounting/exceptions`** | `acc.exception_dashboard.view` (Collections roles get the banner subset through the card) | Filters: `legal_entity`, `adapter`, `status`, `error_class` (`VALIDATION, PERIOD_LOCKED, VOID_UNSUPPORTED, RETRY_EXHAUSTED, CONTACT_NOT_FOUND, AMOUNT_DIFF, WEBHOOK_UNPARSEABLE, CLAIM_EXPIRED, NO_PAYMENT_METHOD, MISMATCH`), `kind`, `age_bucket`, `owner_role`, `sla_breached`, `customer_uid`, `contract_uid` | Page of `PostingException`, read **from the single view `accounting.v_posting_exception`** | — |
| GET | `/accounting/exceptions/summary` | `acc.exception_dashboard.view` | query `date` | `DailyExceptionDashboard` tiles | — |
| POST | `/accounting/exceptions/{uid}:retry` | `acc.exception.retry` | IK, IM; `{ "reason": "..." }` | **202 Job**; exception row `last_retry_by` | `posting_not_retryable`, `posting_already_posted` |
| POST | `/accounting/exceptions/{uid}:redate` | `acc.exception.redate` (ACCOUNTING only) | IK, IM; `{ "new_effective_date": "...", "reason": "..." }` | 201 new `Transaction` with `closed_period_override: true`; original FAILED resolution REDATED | `closed_period` |
| POST | `/accounting/exceptions/{uid}:close-with-reference` | `acc.exception.close_with_reference` (ACCOUNTING only) | IK, IM; `{ "peak_document_id": 123456, "peak_document_code": "IV2026...", "reason": "..." }` | `Posting` POSTED `matched_by: MANUAL` **after GET verification** | `peak_reference_mismatch` |
| POST | `/accounting/exceptions/{uid}:withdraw` | `acc.exception.withdraw` | IK, IM; `{ "reason": "...", "approval_modification_uid": "..." }` | `Posting` FAILED resolution WITHDRAWN plus reversal | `approval_authority` |
| POST | `/accounting/mismatches/{uid}:resolve` | `acc.mismatch.resolve` (ACCOUNTING only) | IK, IM; `{ "resolution": "LINK" \| "IGNORE" \| "ESCALATE", "linked_transaction_uid": null, "reason": "..." }` | `ReconcileMismatch` RESOLVED | — |
| GET | `/accounting/postings` | `acc.posting.view` | Filters: `legal_entity`, `adapter`, `posting_status`, `kind` (`PENALTY, ADJUSTMENT, NEW_SERIES, RESTRUCTURE_VOID, RESTRUCTURE_CN, WRITEOFF_CN, CORRECTION_VOID`), `contract_uid`, `effective_date_from`, `effective_date_to` | Page of `Posting` (transaction, idempotency_key, attempts, external_ref, external_code, document_link, online_view_link) | — |
| GET | `/accounting/postings/{uid}` | `acc.posting.view` | none | `Posting` with **every** `PostingAttempt` (res_code, res_desc, correlation id, masked bodies) | — |
| GET | `/accounting/reconcile-runs` | `acc.posting.view` | Filters `from`, `to` | Page of `ReconcileRun` | — |
| POST | `/accounting/reconcile-runs` | `acc.reconcile.run` | IK; `{ "from_date": "...", "to_date": "...", "scope": "ALL" \| "CONTRACT", "contract_uid": null }` | **202 Job** | `job_already_running` |
| GET | `/accounting/adapters` | `acc.posting.view` | none | List of `Adapter` per legal entity — **SPV → PEAK configured; EPC → NOT_CONFIGURED** — environment, circuit state, billable creates this month against quota | — |

**The dashboard's binding invariant, quoted twice in the spec** (Spec §19.4):

> The alert condition and the screen filter read from the same query, so they can never disagree.

TC-KPI-052 and TC-KPI-053 enforce it as a contract test: "both call one database function `daily_exception_query`, asserted by a code test that no second SQL statement selects non-posted transactions"; a developer changing only the screen filter **fails the build**.

Dashboard tiles (`GET /accounting/exceptions/summary`, from PEAK_Integration.md §7.3):

| Tile | Definition (from the same view) |
|---|---|
| Open exceptions | count by status and error class, today versus yesterday |
| SLA breaches | rows with `business_days_open` greater than 1, by owner role; **target 0** |
| Oldest open | top 10 by age with owner |
| Failed postings value | sum of amount for FAILED OUTBOUND rows |
| Unconfirmed claims | payment claims PENDING over the expiry and their total |
| Reconciliation health | last run time, duration, documents listed, mismatches raised and resolved, webhook events received in the last 24 hours |
| Billable creates this month | count of billable successes against the PEAK package quota |

The Manager's Daily Exception Dashboard content (REQ-KPI-009 and TC-KPI-051) is seven groups: **non-posted transactions, PRE_COLLECTION holds past first due, unmatched receipts, claimed payments awaiting confirmation, promises broken overnight, holds expiring today, integration failures** — "each filterable by entity, adapter, status and age".

Terminal PEAK error classes that become exception rows rather than retries: `VALIDATION, PERIOD_LOCKED, VOID_UNSUPPORTED, CONTACT_NOT_FOUND`. A bulk retry answers **PARTIAL** with one result line per exception.

### 6.8 Recovery board (MOD)

| Method | Path | Permission | Request | Response | Errors |
|---|---|---|---|---|---|
| GET | `/recovery-cases` | `mod.modification.view` | Filters: `status`, `path`, `contract_uid` | Page of `RecoveryCase` | — |
| **GET** | **`/contracts/{uid}/recovery-case`** | `mod.modification.view` | none | `RecoveryCase` with open `paths` rows (**A, B, C, D as a set**; plus the `LEGAL_DEFICIENCY` sub-path) and the D-16 default-model block: assignment deed, buy-back **90 percent of remaining principal**, uninstall fee **10 percent**, removal fee **THB 5 per watt** | — |
| POST | `/contracts/{uid}/recovery-case/paths` | `mod.recovery.open_path` | IK; `{ "path": "A" \| "B" \| "C" \| "D" \| "LEGAL_DEFICIENCY", "reason": "..." }` | 201 `RecoveryPath` (`opened_at`, `opened_by`) | `collateral_required` (C, D), `recovery_path_closed` |
| POST | `/recovery-paths/{uid}:close` | `mod.recovery.close_path` | IK, IM; `{ "reason_code": "AGREEMENT_COMPLIED" \| "REMOVAL_COMPLETE" \| "ACCOUNT_CLOSED" \| "OTHER", "detail": "..." }` | `RecoveryPath` CLOSED (**never deleted**) | — |
| POST | `/recovery-cases/{uid}/assignment-deed` | `mod.recovery.record_assignment_deed` | IK; `{ "effective_date": "...", "remaining_principal": "...", "buy_back_pct": "0.90", "uninstall_fee_pct": "0.10", "removal_fee_per_watt": "5.00", "system_size_watts": 10000, "signed_upload_uid": "..." }` | 201 `AssignmentDeed`; ACC postings queued; ASSIGNMENT_DEED document job | `approval_authority` |
| POST | `/recovery-cases/{uid}/repossession:propose` | `mod.recovery.propose_repossession` | IK; `{ "reason": "...", "collateral_uids": ["…"] }` | `Modification` REPOSSESSION REQUESTED (Manager proposes, COO or CEO approve, Legal and Operations steps) | `collateral_required` |
| POST | `/recovery-cases/{uid}/costs` | `mod.recovery.open_path` | IK; `{ "kind": "LEGAL_FEE" \| "COURT_COST" \| "REMOVAL_COST", "amount": "...", "effective_date": "...", "legal_entity": "SPV" }` | 201 `Transaction` FEE | `closed_period` |
| GET | `/npl-cases` | `mod.modification.view` | Filters: `status` (`UNDER_REVIEW, FLAGGED, HANDED_TO_LEGAL, CLOSED`), `officer_uid`, `dpd_from` | Page of `NplCase` | — |
| POST | `/contracts/{uid}/npl-cases` | `mod.npl.assess` | IK; `NplAssessment` with each Spec §18.3 criterion answered: `dpd_above_30, consecutive_months_unpaid, broken_promise_count, engagement, service_issue_in_progress, restructure_in_progress, restructure_broken_within_6m, service_agreement_lapsed` | 201 `NplCase` UNDER_REVIEW | `npl_excluded_service_issue` |
| POST | `/npl-cases/{uid}:decide` | `mod.npl.flag` | IK, IM; `{ "decision": "FLAG" \| "ATTEMPT_RESTRUCTURE" \| "ALLOW_MORE_TIME", "reason": "...", "review_on": "..." }` | `NplCase`; **FLAG** sets lifecycle NON_PERFORMING, stamps `npl_first_flagged_at` **once**, emits NPL_FLAGGED, creates the LEGAL_HOLD | `npl_auto_flag_forbidden`, `illegal_transition` |
| POST | `/npl-cases/{uid}:handoff-legal` | `mod.npl.handoff_legal` | IK, IM; `{ "note": "..." }` | `NplCase` HANDED_TO_LEGAL; CASE_FILE document job (202) | — |
| GET | `/npl-cases/monthly-report` | `mod.npl.flag` | query `month` | `NplMonthlyReport` | — |
| GET | `/contracts/{uid}/collateral` | `mod.collateral.view` | none | List of `Collateral` (asset_type, identifier nullable, install_location, install_date, condition, `estimated_recovery_value` **labelled estimate**, status ∈ `ON_SITE, SCHEDULED_FOR_RECOVERY, RECOVERED, DISPOSED, NOT_RECOVERABLE`) | — |
| PATCH | `/collateral/{uid}` | `mod.collateral.manage` | IM; `{ "status": "...", "reason": "...", "estimated_recovery_value": "...", "identifier": "..." }` — **NOT_RECOVERABLE requires reason** | `Collateral` | `illegal_transition` |
| POST | `/collateral/{uid}:relink` | `mod.collateral.manage` | IK, IM; `{ "contract_uid": "..." }` | `Collateral` | — |
| GET | `/modifications` | `mod.modification.view` | Filters: `type` (`PENALTY_WAIVER, SERVICE_ISSUE_FREEZE, RESTRUCTURE, PAYMENT_HOLIDAY, REDUCE_INSTALMENT, EXTEND_TERM, CONTRACT_CANCELLATION, REPOSSESSION, WRITE_OFF`), `status` (`REQUESTED, APPROVED, REJECTED, EFFECTIVE`), `contract_uid`, `requester_uid`, `approver_uid` | Page of `Modification` | — |
| GET | `/modifications/{uid}` | `mod.modification.view` | none | `Modification` with typed `payload`, `approval_route` (steps, who, when, **authority checked as at approval date**), `before`, `after` | — |
| POST | `/modifications/{uid}:approve` | per-type route | IK, IM; `{ "decision_note": "...", "approved_on": "..." }` | `Modification` APPROVED when all route steps done; **joint routes stay REQUESTED with `pending_steps`** | `approval_authority`, `approval_ratify_after_forbidden`, `candidate_schedule_missing` |
| POST | `/modifications/{uid}:reject` | same as approve | IK, IM; `{ "reason": "...", "follow_up_path": "STANDARD_COLLECTION" \| "CANCELLATION_REVIEW" \| "LEGAL" }` | `Modification` REJECTED; candidate schedule discarded with an audit row — **"leaves no orphan"** | — |
| POST | `/contracts/{uid}/write-offs` | `mod.write_off.propose` | IK; `amount`, `evidence_upload_uids[]`, `reason`, `recovery_value_applied` | 201 `Modification` WRITE_OFF REQUESTED — **Owner or formal delegate approves; Manager never approves** | — |

**Recovery paths A/B/C/D** (Collection_Workflow_Alignment.md §5.2, Spec §11a.3):

| Path | Action | Trigger | Owner | App behaviour |
|---|---|---|---|---|
| A | Negotiation and restructure | Customer engaged, cause identified | Credit & Risk only | Opens the Restructure wizard or a payment arrangement; closes when an approved agreement exists and is being complied with |
| B | Legal action | Customer non-engaged or unreachable, or flagged non-performing | Legal / Recovery, with management approval | Legal hand-off package; LEGAL_STATUS register; lifecycle LEGAL on acceptance; **referring to litigation does not automatically stop contact** |
| C | Equipment removal | Lease agreement where VOLT retains ownership | SCM removal, Service/O&M dispatch, management approval | REPOSSESSION modification; **requires at least one resolved collateral row**; work order PDF |
| D | Legal action together with removal | Both B and C in parallel | Legal, Recovery, SCM, Service/O&M, management | Both paths open in the set; a Path D coordination panel |

The board's structural rule, verbatim:

> recovery state is a set held as `contract_recovery_path` rows, never a single column; the control is a multi-select showing every open path with when it opened and who opened it; there are no forbidden pairs, but the mutual-exclusion guard exists as a no-op hook; a track closes when an approved agreement is being complied with, when removal completes, or when the account closes; **a path is never deleted, it closes with a reason and a timestamp**.

Contract lifecycle statuses (REQ-MOD-018), exactly twelve: `PENDING_ACTIVATION, PRE_COLLECTION, ACTIVE, PAST_DUE, MORATORIUM, RESTRUCTURED, NON_PERFORMING, LEGAL, REPOSSESSED, SETTLED, WRITTEN_OFF, CANCELLED`. "the transition matrix is data; an illegal transition is rejected **naming it**; every transition audits actor, both dates and reason."


---

## 7. Board rules — the daily-slot model

The section preamble is quoted in the test file as a binding rule (Spec §8):

> **This section implements Thai law. It may not be merged, simplified, or replaced by a vendor pattern.**

And the assignment rule (Spec §7.1):

> Assignment is at the customer level, keyed on `citizen_id` for individuals or `juristic_id` for entities — never at the contract level. **A customer holding several contracts has one officer and receives one contact covering all of them.**

### 7.1 The three counting rules (REQ-COL-012, Spec §8.1)

> outbound, answered, officer states the amount **counts**; outbound, answered, but the customer hangs up or says it is inconvenient **does not count and the officer may retry**; inbound, customer-initiated **never counts and is unlimited**

### 7.2 Channel counting (REQ-COL-013, Spec §8.2)

> phone outbound counts **only** when the result is Answered with `amount_discussed_y_n = true`; phone outbound Answered not discussed does not count; inbound call never counts; **LINE outbound counts only on confirmed read receipt**; SMS and email never count; auto-invoice and pre-due reminders never count

The LINE case is subtle and matters for the UI (§8.5, verbatim):

> the contact row is created immediately with `counted: false`, and the `READ` status callback **flips `counted` to true and takes the daily lock at the moment of the read, not at the moment of the send**. A `BLOCKED` callback leaves `counted: false` and raises the blocked flag

TC-COL-027 makes the timing concrete: message sent 10:00, read receipt 14:20 → "a call attempted at 12:00 is therefore allowed and one at 15:00 is blocked."

### 7.3 Contact dispositions — the closed dictionary

REQ-COL-014, verbatim, dictionary list `contact_result`:

> Answered amount discussed (**counts**); Answered not discussed (no, may retry); Voicemail left, no answer, busy, disconnected, wrong number (no); Read for LINE (**counts**); Sent unread (no); Sent blocked (no, **plus a flag on the customer**); Inbound customer called (never)

| Disposition | Direction / channel | Counts? | Side effect |
|---|---|---|---|
| Answered, amount discussed | OUTBOUND / PHONE | **yes** | Consumes the slot; writes PERSON + CONTRACT lock rows |
| Answered, not discussed | OUTBOUND / PHONE | no | Officer may retry the same day |
| Voicemail left | OUTBOUND / PHONE | no | Recorded; attempt appears in history and in the officer activity KPI |
| No answer | OUTBOUND / PHONE | no | " |
| Busy | OUTBOUND / PHONE | no | " |
| Disconnected | OUTBOUND / PHONE | no | " |
| Wrong number | OUTBOUND / PHONE | no | " |
| Read | OUTBOUND / LINE | **yes, at read time** | Lock consumed at `line_read_at`, not at send |
| Sent unread | OUTBOUND / LINE | no | — |
| Sent blocked | OUTBOUND / LINE | no | **Raises a flag on the customer** (`raises_flag` attribute on `LINE_BLOCKED`) so the officer stops using that channel |
| Inbound, customer called | INBOUND / any | **never** | Unlimited; `inbound_call_does_not_count` is LOCKED **law** — "no override, no Manager action and no configuration edit can make an inbound call count" |
| SMS sent | OUTBOUND / SMS | never | Category NOTIFICATION; "the rule is a channel property, not a result property" |
| Email sent | OUTBOUND / EMAIL | never | " |
| Pre-due reminder / auto-invoice | system | never | `officer_user_id: null`, category NOTIFICATION; several per customer per day permitted subject to rate limiting |

**Code vocabulary is inconsistent across the repo — see §12.2.** The test cases use short codes that fit the 16-character dictionary cap (`ANS_DISCUSSED`, `ANS_NOT_DISC`, `LINE_BLOCKED`); the API worked examples use long ones that do not (`ANSWERED_AMOUNT_DISCUSSED` is 25 chars).

Channel enum from the event contract: `PHONE, LINE, SMS, EMAIL, VISIT, LETTER`.
Direction enum: `INBOUND, OUTBOUND`.
Stakeholder type enum (PRD REQ-COL-017, TC-COL-041, Event_Contracts §4.3): `PRIMARY_BORROWER, CO_BORROWER, GUARANTOR, THIRD_PARTY, ESTATE`.

### 7.4 The lock itself

| Rule | Detail |
|---|---|
| Limit | `daily_contact_limit_per_customer` = **1 per customer per day**, outbound with amount discussed only. **LOCKED law.** |
| Key | The customer's identity key (`identity_hash` from citizen id or juristic id), **not** the contract. |
| Day boundary | The **Asia/Bangkok calendar day**. TC-COL-037: a contact at 23:50 Bangkok on the 23rd and another at 00:10 on the 24th are both allowed, even though both fall on 2026-10-23 in UTC. "every lock query resolves the date with the Asia/Bangkok timezone rather than the server default" |
| Cross-channel | One shared guard. TC-COL-031: a phone call at 09:10 blocks a LINE message at 11:05 — "the second channel is not a way around the first" |
| Two stored levels | A counting contact writes **two** rows: one at level PERSON keyed on `identity_hash`, one at level CONTRACT keyed on the contract. Both are always stored even when only PERSON is enforced. `contact_lock_levels` is LOCKED pending Legal. "the two levels **must not be optimised away**" |
| Joint borrowers (interim) | Once a counting contact succeeds and any co-borrower has acknowledged it, contacting the other co-borrowers **on that contract** is blocked for the day. The blocked party gets 409 `contact_locked` citing the **contract-level** lock even though their own person lock is absent |
| Race safety | TC-COL-036: two officers submitting within 50 ms → exactly one 201 with `lock_consumed: true`, the other 409. Enforced by a **unique partial index on `(lock_date, identity_hash)`**, not by application logic. "no partial activity row is left behind by the losing transaction" |
| Unsuccessful attempts | Still logged, with `counted: false` and `blocked_by_lock_id` set to the existing lock. "the lock is not extended, duplicated or released" |
| Substitutes | A substitute officer consuming the slot consumes it for the customer, so the returning primary cannot contact them again the same day |
| Mark-as-contacted | One `POST /customers/{uid}/contacts:mark-contacted` writes one activity covering all contracts, **one PERSON lock and one CONTRACT lock per contract**, `counted: true`, and consumes exactly **one** slot |
| Manager override | Permitted **only** with a logged reason. Without → 422 `override_reason_required` and nothing written. With → 201, `override: true`, `override_by_user_id`, `override_reason`, `blocked_by_lock_id`, and **no second lock row**. Audited and on the compliance report |
| Who may override | Manager and Owner only. Officer and **Supervisor** both get 403 — "the daily limit is not a soft guideline that a persuasive officer can pass" |
| CONTACT_HOLD interaction | 409 `contact_on_hold`, **distinct from `contact_locked`**; no lock row created or consumed; reminders written SUPPRESSED with `suppression_cause: HOLD`. "when the hold expires the customer's daily slot is intact and unused, so the hold has not silently spent it" |

### 7.5 The four contact-action UI states (REQ-COL-016, TC-COL-032)

Returned **by the server, not computed in the browser**:

| State | Meaning |
|---|---|
| `READY` | Buttons active — no counting contact today |
| `LOCKED` previous officer / `LOCKED_OTHER` | Greyed; shows "contacted today by *officer* at *time* with result *result*" |
| `LOCKED` self / `LOCKED_SELF` | Greyed; shows the officer's own earlier contact |
| `OVERRIDE` | Available to Manager; **reason required before the action proceeds** |

(See §12.3 — the API endpoint's own enum is `OPEN / LOCKED / ON_HOLD`, three values, which does not line up with these four.)

### 7.6 Reminders never count (§8.5, the enforcement table)

| Rule | Implementation |
|---|---|
| Separate resources | Reminders are created by the system and read at `GET /v1/reminders`; **there is no endpoint by which a user creates a reminder as a contact or converts one into a contact.** Contacts are created only at `POST /v1/contacts` and `POST /v1/customers/{uid}/contacts:mark-contacted` |
| Separate permissions | `col.reminder.view` and `col.reminder.suppress` never grant `col.contact.log`, and the reverse holds |
| The lock is not consulted | The notify gateway does not read the contact lock and does not take it. A customer already contacted today still receives the T-3 reminder; a customer who received three reminders today can still be contacted once by an officer |
| The counter is not moved | Reminder rows never set `counted`, never appear in the daily-limit query, and are **excluded from the compliance report** |
| Visible but distinct | Card and Today List item show reminders and contacts in one timeline with different type badges |
| Audit | `feature_id` `col.reminder.send` versus `col.contact.log`, "so a regulator-facing report can be produced without joining on message content" |

Consequence for clients, verbatim:

> never infer "the customer was contacted" from a reminder row, and never render a reminder in a component that reports against the daily limit. **The authoritative signal is the `contact_lock` object** on the customer, the contract card and the Today List item.

Reminder schedule (REQ-COL-023, Spec §9.4): in good standing **T-3, T-0, T+7, T+13 (four touches)**; late-payment history or high-risk **additionally T-7, T+3, T+10 (seven maximum, never an eighth)**. Points come from `config.reminder_schedule`, not constants. Sending stops immediately on payment, on entry to any Service or Dispute hold, or once a new agreement exists; a customer placed with an external agency receives nothing. Sends are de-duplicated across channels by `dedupe_key` on `(customer, planned_for, point, channel)`. `risk_class` is stamped on each row **at planning time** so a later band change does not rewrite history.

### 7.7 The Today List / work-queue model

| Rule | Detail |
|---|---|
| Generation | Daily at **02:30 Asia/Bangkok**, after the **02:00** DPD recalculation completes. If 02:00 has not completed, the 02:30 job **waits and, on timeout, fails loudly with an alert rather than generating from stale DPD** |
| Before a successful run | `GET /v1/today-list` returns **503 `today_list_not_ready`** with `Retry-After` and `extensions.last_run` |
| Entry mode | **Event-driven at 1 DPD**; the 02:30 batch is "an idempotent reconciling safety net that may never create a duplicate". Running the batch twice creates nothing further |
| Grouping | By **customer, never by contract**. One item per customer with `contract_ids` listing all of them, `total_arrears` summed and `oldest_dpd` |
| One item, strongest reason | A customer qualifying for two priorities gets **one** item at the higher priority; the weaker qualification appears in `secondary_reasons`, never as a second row |
| Idempotent regeneration | A partial run is **superseded, not duplicated**; a unique index enforces one SCHEDULED run per `run_date` |
| Sort | Default `priority` ascending. Also `risk_score` and `oldest_dpd`. "Sorting changes only the order and never the membership" |
| Visibility | Officer sees own assigned customers only (403 otherwise). Supervisor sees their team; Manager sees anyone. **Sales read-only gets 403.** Every cross-officer view is audited |

Priorities (REQ-COL-008, Spec §13.2), 1 highest to 6 lowest:

| # | Priority | Reason code seen in examples |
|---|---|---|
| 1 | Promise due today | `PROMISE_DUE_TODAY` |
| 2 | Broken promise | `BROKEN_PROMISE` |
| 3 | Scheduled next call — reads `scheduled_next_contact_at` | — |
| 4 | Status changed alert (service issue resolved, restructure due, service agreement status changed) | — |
| 5 | Mid overdue DPD 8–29 | — |
| 6 | Early overdue DPD 1–7 | — |

*(The §5.8 worked example shows `priority: 1` with `reason_code: "BROKEN_PROMISE"` and `priority: 2` with `PROMISE_DUE_TODAY` — inverted relative to REQ-COL-008. See §12.4.)*

Priority-3 lifecycle (REQ-COL-009, TC-COL-020) — the one rule most likely to be got wrong:

> A priority-3 case shall appear under **Upcoming one day ahead**, appear on the list on the day, and **remain until explicitly marked Completed; it does not roll off silently**

Concretely: on D-1 the item exists with `is_upcoming: true`, status `UPCOMING`; on D it is `OPEN` at priority 3; on D+1 it is **still present** with status `CARRIED_OVER` and `carried_from_item_id` set. Marking it Completed with an outcome code is the only way it leaves the list.

### 7.8 Arrears — what it is and where it comes from

REQ-COL-027, the required order, verbatim:

> total arrears payable today; days past due and aging bucket; accrued penalty with the composition of the arrears; next due date; next instalment amount; full payoff; **all figures computed server-side and returned by one endpoint sourced from the daily ledger, so header and drill-down agree to the satang**

Aging buckets (REQ-MNY-016, Spec §12.2). These are **seeded reference data in `ref.aging_bucket`, not a configuration key** — "a change is a migration, not a panel edit":

| Bucket | DPD | Colour | Today List priority |
|---|---|---|---|
| Current | 0 | green | — |
| Early Overdue | 1–7 | yellow | 6 |
| Mid Overdue | 8–29 | orange | 5 |
| Risk Review | **30 or more** | red | — (NPL eligibility starts) |
| NPL Confirmed | — | black | Manager-flagged only |
| Resolved | — | green | — |
| Closed | — | grey | write-off or cancellation |

Bucket boundaries are **inclusive at the lower edge**: TC-KPI-022 — a contract at exactly DPD 30 is inside Risk Review and inside the PAR30 numerator; DPD 29 is Mid Overdue and outside it. Same inclusive rule at 60 and 90.

What is in arrears, from the multi-contract aggregate (TC-COL-053): aggregate overdue across contracts, total penalty accrued across both, oldest DPD. **Penalty accrued, billed, paid and waived are four separate figures and are never netted into one.**

What DPD is frozen by: a `PENALTY_SERVICE_HOLD`. While frozen, daily-ledger rows carry `service_issue_frozen: true` and `penalty_accrued_today: 0.00`, and the contract carries `excluded_from_kpi: true`.

---

## 8. KPI definitions

Fourteen indicators: nine core (Spec §20.1) plus five portfolio risk (Spec §20.2), plus derived ones. Codes from TC-KPI-001:

`COLLECTION_AMOUNT` 1, `FOLLOW_UP_COMPLETION` 2, `PROMISE_AMOUNT` 3, `PROMISE_KEPT_RATE` 4, `BROKEN_PROMISES` 5, `CURE_ROLLBACK` 6, `BUCKET_CONTROL` 7, `CONTACTABILITY` 8, `CASE_CLOSED` 9, `LOAN_TO_DEPOSIT` 10, `PAR_30` 11, `PAR_60` 12, `PAR_90` 13, `NPL_RATIO` 14, plus `RESTRUCTURE_KEPT_RATE`, `RESTRUCTURE_BROKEN_RATE`, `LOAN_SCORE_PASS_RATE`.

Each definition carries `formula_text` **verbatim from the spec**, plus `unit`, `direction` and `refresh_mode`. Every indicator response carries `basis`, `snapshot_at` and `computed_by`; "an indicator without both fields fails the schema test".

### 8.1 The nine core indicators (REQ-KPI-001, verbatim)

> 1 collection amount (actual collected, **primary**); 2 follow-up completion (accounts with required actions completed per cycle); 3 promise amount (total under active promises); 4 promise kept rate ((full kept + partially kept × weight) ÷ total, weight per `ptp_kept_partial_weight`); 5 broken promises (count and amount below the partial threshold); 6 cure or rollback (accounts that improved bucket or resolved); 7 bucket control (month-on-month slide prevention); 8 contactability (reachable, unreachable, requires-retry rates); 9 case closed (paid in full, returned to current, sent to Legal, restructure success)

MVP note on that row: "**Indicators 1, 2 and 8 are MVP on the officer dashboard.**"

### 8.2 Numerator and denominator, indicator by indicator

Worked from the reference fixture (FX-MONTH: officer FX-OFF1, September 2026; FX-PORT: 100 active contracts, 2,000,000.00 outstanding).

| # | Indicator | Denominator **includes** | Denominator / numerator **excludes** | Worked value |
|---|---|---|---|---|
| 1 | Collection amount | **Confirmed allocations by value date** | A PENDING bank-slip claim is **never** in it (reported separately as `claims_pending`). Confirming later with a September value date moves it into September "as a dated adjustment, not a silent restatement" | 64,195.00 |
| 2 | Follow-up completion | Today List items requiring an action in the cycle (40) | An item that rolls into the next day **without** being marked Completed **stays in the denominator and does not silently roll off** | 34 ÷ 40 = 0.85000 |
| 3 | Promise amount | Promises in status **Active at the as-of instant**, measured **by amount, not by number of contracts** | — | 24,740.00 |
| 4 | Promise kept rate | All promises reaching their date in the period (10) | **Returns null** while `ptp_kept_partial_weight` is unset | (6 + 2×0.5) ÷ 10 = 0.70000 |
| 5 | Broken promises | Promises below `ptp_partial_threshold_percent` | A promise paid **exactly at** the threshold is Partially Kept, not Broken — **the boundary is inclusive of the threshold**. Null while the threshold is unset | count 2, amount 13,580.00 |
| 6 | Cure and rollback | Accounts that improved bucket **or** resolved | An account moving Risk Review → Resolved counts **once, under resolved**, never double-counted | 5 (improved 3, resolved 2) |
| 7 | Bucket control | **Accounts open at BOTH month ends** (100) | **Accounts opened during the month and accounts closed during the month are excluded from both numerator and denominator** | 1 − 7÷100 = 0.93000 |
| 8 | Contactability | **Outbound attempts only** (120) | **The 9 inbound calls are excluded from the denominator** because an inbound call never counts (`inbound_call_does_not_count`, LOCKED law) | reachable 0.55, unreachable 0.25, requires_retry 0.20 — the three **sum to 1.00000** |
| 9 | Case closed | Four outcomes only: paid in full, returned to current, sent to Legal, restructure success | **A contract closed by write-off or cancellation appears in neither the total nor the breakdown**, because Spec §20.1 lists four outcomes only | 8 (2/4/1/1) |
| 10 | Loan-to-deposit | Σ outstanding principal ÷ Σ down payment collected. Target **≤ 4×** | — | 1,800,000 ÷ 400,000 = 4.5000 → **BREACH** |
| 11 | PAR30 | Σ outstanding on contracts DPD **≥ 30** ÷ Σ total outstanding. Target **≤ 5 %** | — | 120,000 ÷ 2,000,000 = 0.06000 → BREACH |
| 12 | PAR60 | same shape, DPD ≥ 60. Target **≤ 3 %** | — | 0.02500 → MET |
| 13 | PAR90 | same shape, DPD ≥ 90. Target **≤ 2 %** | — | 0.01500 → MET |
| 14 | NPL ratio | **Manually flagged** population ÷ total. Target **≤ 1.5 %** | Automatic threshold flagging does not exist — `npl_dpd_threshold_days` is unset, so the population is the manually flagged one only | 2 ÷ 100 = 0.02000 → BREACH; snapshot stores **both** the count basis (2 of 100) and the amount basis (30,000 of 2,000,000) and labels which is the headline |

**The PAR denominator is identical for 11, 12 and 13**, so "the three ratios are strictly ordered par_30 ≥ par_60 ≥ par_90".

### 8.3 The two global exclusions — get these right or every ratio is wrong

1. **PRE_COLLECTION contracts.** DPD is `null`. TC-KPI-024: the 4 PRE_COLLECTION contracts are excluded from **every PAR numerator and from the PAR denominator**, and reported separately as `precollection_contracts: 4`. "including them in the denominator would understate the ratios, so the test asserts the denominator is 2,000,000.00 and not the larger figure."

2. **Service-issue-held accounts** (REQ-KPI-007, Spec §16.1). TC-KPI-025: contracts under `PENALTY_SERVICE_HOLD` are excluded **from the officer KPI denominators and from the non-performing assessment for the days held**; their frozen DPD does not move any account into a worse bucket, so indicator 7 is unaffected. But — "**they remain visible on the portfolio outstanding total, which is a balance sheet figure and not a performance figure.**"

3. Synthetic traffic is excluded from KPI counts via `X-Debt-Client` (§2.3).

### 8.4 Empty denominators (TC-KPI-015)

> Rate indicators return **null with denominator 0** rather than 0.00000 or a division error; count and amount indicators return 0 and 0.00; the dashboard renders "no data" and not "0 percent", **so an idle month is never mistaken for a failed month**

### 8.5 Refresh, reproducibility and the pending-config pattern

| Rule | Detail |
|---|---|
| Primary path | **Event-driven, incremental on each event**, counters move within one second of the Pub/Sub push. `basis: INCREMENTAL` |
| Snapshot | Materialised on a **five-minute boundary**, `computed_by: SNAPSHOT`, one row per `(kpi_code, scope, scope_id, legal_entity)` |
| Reconciliation | Nightly `kpi-reconcile` at **03:15** Asia/Bangkok (spec says 03:00; deviated so `peak-reconcile` at 03:00 finishes first). "The daily run is a reconciliation backup, **not the primary path**" |
| On divergence | The incremental snapshot row is **not edited, it is superseded**; a reconciliation exception is recorded naming the indicator and both values |
| Idempotency | Consumers are idempotent on event id; a redelivered event moves the counter once |
| Entity discipline | An event with no `legal_entity` is **dead-lettered, never folded into SPV**; no portfolio figure changes |
| Staleness | Metric `debt.kpi.snapshot_age_seconds`, P3 alert above **900 s**. Dashboards "continue to render the last good snapshot with its `snapshot_at` shown, and never render a stale figure as if it were current" |
| Reproducibility | Each snapshot stores the **query version and the configuration values in force at `as_of`**, and the `target_value` in force then. Re-reading September after an October config change still returns the September number |
| Unset configuration | Return **null plus a banner**, never a guessed default. TC-KPI-008: `promise_kept_rate` returns null with `pending_confirmation: true`, `reason: ptp_kept_partial_weight_not_set`, `owner: Debt Manager`. "**no default of 1.0 or 0.5 is assumed anywhere**" |
| Masking | Exports apply the same masking as the screens; identity numbers masked to the last four digits, bank identifiers masked, phone and email absent. A cell beginning with `=` is prefixed with a single quote so a spreadsheet cannot execute it |

### 8.6 KPI endpoints

| Method | Path | Permission | Request | Response |
|---|---|---|---|---|
| GET | `/kpis` | `kpi.dashboard_officer.view` and up | `scope` (`OFFICER, TEAM, PORTFOLIO`), `subject_uid`, `period` (`2026-09` or a range), `as_of` | `KpiSet`: nine core + five portfolio risk, each with `target`, `actual`, `status`, `snapshot_at`, `basis: INCREMENTAL \| RECONCILED` |
| GET | `/kpis/{kpi_code}/series` | same | `scope`, `subject_uid`, `from`, `to`, `grain` (`DAY, MONTH`) | Time series |
| GET | `/kpis/definitions` | **any authenticated** (no `x-permission`) | none | Definitions and formulas, spec wording |
| GET | `/dashboards/officer` | `kpi.dashboard_officer.view` | `officer_uid` (self default) | `OfficerDashboard` |
| GET | `/dashboards/team` | `kpi.dashboard_team.view` | `team_uid` | `TeamDashboard` |
| GET | `/dashboards/portfolio` | `kpi.dashboard_portfolio.view` | none | `PortfolioDashboard` with aging distribution and risk indicators |
| GET | `/dashboards/owner` | `kpi.dashboard_owner.view` | none | `OwnerDashboard` — aggregates plus items awaiting approval |
| POST | `/dashboards/{name}/exports` | `kpi.export.create` | IK; `{ "format": "CSV" \| "XLSX", "filters": {...} }` | **202 Job** → `Export` |
| GET | `/exports/{uid}` | same | none | `Export` with `url` (signed, **10 minutes**, re-issuable until `expires_at` **7 days**) |
| GET | `/portfolio/daily` | `kpi.dashboard_portfolio.view` | `from`, `to` | Page of `PortfolioDaily` rows |
| GET | `/kpi-targets` | `cfg.kpi_target.manage` or `kpi.dashboard_team.view` | `scope`, `period` | List of `KpiTarget` (**history preserved**) |
| PUT | `/kpi-targets/{scope}/{subject_uid}/{period}` | `cfg.kpi_target.manage` | IK, IM; `{ "targets": { "collection_amount": "...", "promise_kept_rate": "0.85" } }` | `KpiTarget` (old value audited) |

Scope enforcement is 404, not 403 (TC-KPI-037): "HTTP **404 `not_found` rather than 403, so officer identifiers cannot be enumerated**; an audit access row records the attempt."

Export inherits the dashboard's view permission (TC-KPI-045): an officer POSTing to `/dashboards/portfolio/exports` gets 403.

---

## 9. Rate limits

Per-principal, sliding window in Memorystore. **Fails open for authenticated users and closed for webhooks** when Redis is unavailable. Cloud Armor adds per-IP limits in front (600/min per IP, ban at 1,200; `/v1/auth/*` 30/min per IP).

| Scope | Limit |
|---|---|
| General authenticated | 600 requests per minute |
| Write endpoints (POST, PATCH, DELETE under `/v1`) | 120 per minute |
| Money-creating or PEAK-bound POST | 30 per minute |
| Reveal endpoints (`:reveal`) | 30 per hour, **and at most 5 per customer per day per user** |
| Document URL issuance | 120 per hour |
| Exports | 10 per hour; **personal-data exports 3 per day** |
| **Today List full fetch** | **60 per minute** |
| Public verification page | 30 per minute |

Every response carries `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` (seconds). 429 responses add `Retry-After`.

---

## 10. Events the prototype may want to emit or consume

From `Event_Contracts.md` §4.3 and §4.12. Envelope is a CloudEvent-style structure with an aggregate/ordering key and a stated idempotency key. **No public endpoint publishes events** — the outbox is internal.

| Event | Producer | Idempotency key | Key payload fields |
|---|---|---|---|
| `evt.collections.contact_logged` | COL, when an officer saves a contact attempt | `contact_id` | `contact_id, customer_id, contract_ids[], officer_user_id, direction, channel, result_code, amount_discussed, counts_toward_lock` (**computed by the guard, not by the UI**), `stakeholder_type, scheduled_next_contact_at, promise_id, service_issue_hold_id, override_by_user_id, override_reason, occurred_at` |
| `evt.collections.ptp_created` | COL, on save | `promise_id` + status | `promise_id, customer_id, contract_id, linked_instalment_no, promised_amount, promised_date, renegotiation_count, supersedes_promise_id, arrangement_id, created_by_user_id, created_at, timer_due_at` |
| `evt.collections.ptp_kept` | COL, "when the allocation engine's classification arrives" | " | — |
| `evt.collections.ptp_broken` | COL, by the durable timer at **02:00 after the promised date**, idempotent for past dates | " (**emitted once per promise**) | — |
| `evt.collections.today_list_generated` | COL, the 02:30 job, once per business day | `as_of_date` | `as_of_date, generated_at, entry_count, officer_counts, suppressed_count, duration_ms` |
| `evt.collections.officer_assigned` | COL, on customer-level assignment or reassignment | `customer_id + assigned_at` | `customer_id, officer_id, previous_officer_id, assigned_at, assignment_reason, contract_ids` |
| `evt.collections.handover_committed` | COL, on commit | `handover_id` | `from_officer_id, to_officer_id or MANAGER_QUEUE, customer_ids, committed_at, handover_id, reason` |
| `evt.collections.service_issue_flagged` | COL, external alias of `hold_opened` when type is PENALTY_SERVICE_HOLD and reason SERVICE_ISSUE | `hold_id` | `contract_id, customer_id, hold_id, opened_at, reason, expected_resolution_date` |
| `evt.accounting.posting_failed` | ACC, on FAILED after the retry budget, or a reconciliation exception | `posting_id + attempts` | `posting_id, contract_id, document_type, error_code, error_message, attempts, failed_at` |
| `evt.accounting.claimed_payment_confirmed` | ACC, when Accounting confirms a PENDING claim — **"the claim itself never changes DPD"** | `claim_id` | `claim_id, contract_id, amount, value_date, confirmed_by, confirmed_at, evidence_document_id` |
| `evt.modifications.recovery_opened` | MOD, when a recovery path row is opened | `contract_id + recovery_path + opened_at` | `contract_id, recovery_path, opened_by, opened_at, collateral_id` |
| `evt.modifications.collateral_changed` | MOD, on any collateral change | `collateral_id + version` | feeds "the `collateral_presence` projection **that gates recovery paths C and D**" |
| `evt.kpi.snapshot_taken` | KPI, on each daily or intraday snapshot | `snapshot_id` | `as_of_date, snapshot_id, cadence, indicator_count, legal_entity, computed_at` |


---

## 11. Configuration keys the board and KPI logic read

Anything here that is unset must produce a **null plus a banner naming the missing key and its owner**, never a guessed default. That is the spec's pattern (A-03) and it is asserted by tests.

| Key | Value in the fixtures | Status |
|---|---|---|
| `daily_contact_limit_per_customer` | 1 per customer per day, outbound with amount discussed only | **LOCKED law** |
| `inbound_call_does_not_count` | true | **LOCKED law** |
| `contact_lock_levels` | PERSON and CONTRACT both stored | **LOCKED pending Legal** |
| `amount_discussed_y_n_required` | true | set |
| `contact_hours_weekday` / `contact_hours_holiday` | `08:00-20:00` / `08:00-18:00` | **LOCKED law**, `PUT` returns `config_locked` |
| `customers_per_officer_cap` | 100 | set |
| `today_list_generation_time` | 02:30 | **platform-managed** — lives in Terraform; `PUT` returns 422 `config_read_only` with `extensions.managed_by: terraform` |
| `dpd_recalculation_time` | 02:00 | platform-managed, same |
| `penalty_accrual_time` | — | platform-managed, same |
| `ptp_autocheck_time` | 02:00 | set |
| `ptp_renegotiation_cap_per_installment` | 2 | set |
| `pre_due_reminder_window_days` | 3 to 5 | set |
| `service_issue_audit_sample_rate` | 10 percent per officer per month | set |
| `hold_reason_required`, `hold_expiry_required`, `hold_types` | true, true, three types | **LOCKED policy** |
| `collection_queue_entry_mode` | event-driven at 1 DPD, batch as reconciling safety net | set |
| `restructure_kept_threshold` / `restructure_broken_threshold` | 3 consecutive / 2 missed in 6 months | set |
| `restructure_max_per_contract` | 2 | **LOCKED policy** |
| `ptp_partial_threshold_percent` | — | **UNSET.** Blocks indicator 5; a promise evaluates to `PENDING_THRESHOLD` with a Debt Manager task, and the broken-promise count is **not incremented** |
| `ptp_kept_partial_weight` | — | **UNSET.** Blocks indicator 4 |
| `arrangement_break_tolerance` | — | **UNSET.** Evaluation applies no tolerance and records `tolerance_days_applied: 0` naming the pending key |
| `npl_dpd_threshold_days` | — | **UNSET.** So indicator 14's population is manually flagged contracts only |
| `restructure_kpi_credit_mode` | — | **UNDECIDED** among `CREDIT_ON_APPROVAL`, `CREDIT_ON_FIRST_KEPT`, `NONE`; PRD proposal is credit on three consecutive kept |
| `penalty_invoicing_enabled` | **true** — superseded 2026-09-09, ruling 87; was **false** | **SUPERSEDED — ruling 87.** Invoicing is ON by default; the flag stays Owner-tunable, and while off `POST /penalties/{uid}:bill` still returns 422 `feature_disabled` |
| `allocation_order.locked` | false | While false, allocation may return 422 `allocation_rule_pending` |
| `accounting_closed_through_date` | — | Drives `closed_period` |

---

## 12. Where the spec disagrees with itself, or with the request

These are the things that will bite an implementer. Each one needs a decision recorded in the prototype, not a silent guess.

### 12.1 The version premise and two named error codes

- **Local docs are all `version: 1.0`, not v2.x.** The v2.1 revisions live in Drive, not in this repo. The *substance* the request was after — doc/build version separate from the wire version — **is** in the text and is quoted verbatim in §1 above.
- **`422 population_filter_unset` and `409 closure_voids_pending` do not exist anywhere in the repo.** Full detail and the nearest real codes are in §5.3. **Do not present them as spec-derived.**

### 12.2 Contact result codes: two vocabularies, one of them illegal

| Source | Codes used |
|---|---|
| `API_Surface.md` §5.2 worked example and §2.4 error example | `ANSWERED_NO_COMMITMENT`, `ANSWERED_AMOUNT_DISCUSSED` |
| `TEST-CASES-COL.md` TC-COL-024 / 025 / 028 | `ANS_DISCUSSED`, `ANS_NOT_DISC`, `LINE_BLOCKED` |

`API_Surface.md` §2.2 states: "**Dictionary codes (Spec §22.5) are at most 16 characters**", and there is a dedicated error for violating it (`dictionary_code_too_long`, DEBT-CFG-0427, 422). `ANSWERED_AMOUNT_DISCUSSED` is **25 characters** and `ANSWERED_NO_COMMITMENT` is **22** — both would be rejected by the API's own dictionary rule. The short forms in the test cases fit.

**Recommendation for the prototype: use the short test-case forms** (`ANS_DISCUSSED`, `ANS_NOT_DISC`, `LINE_READ`, `LINE_SENT`, `LINE_BLOCKED`, `INBOUND_CALL`, `VOICEMAIL`, `NO_ANSWER`, `BUSY`, `DISCONNECTED`, `WRONG_NUMBER`) and flag the API examples as needing a correction. Seed the full list from a `contact_result` dictionary fixture rather than hard-coding.

### 12.3 The contact-lock state enum has two shapes

| Source | Values |
|---|---|
| `API_Surface.md` §4.1, `GET /customers/{uid}/contact-lock` | `OPEN`, `LOCKED`, `ON_HOLD` (3 values) plus `locked_by`, `override_allowed` |
| §5.8 Today List worked example, `contact_lock.state` | `"OPEN"`, `"LOCKED"` |
| REQ-COL-016 and TC-COL-032 (the UI contract) | `READY`, `LOCKED_OTHER` ("LOCKED previous officer"), `LOCKED_SELF`, `OVERRIDE` (4 values) |

Both are satisfiable from one payload: keep the API enum `OPEN / LOCKED / ON_HOLD` and derive the four UI states from `state` + `locked_by.uid == me` + `override_allowed`. TC-COL-032's binding requirement is only that the states are **"returned by the server, not computed in the browser"**, so the derivation must happen server-side and be returned as an explicit field. **Recommendation: return both — `state` (the 3-value enum) and `ui_state` (the 4-value one) — and note it as an additive extension.**

### 12.4 Today List priority ordering in the worked example is inverted

REQ-COL-008 and TC-COL-018 both put **promise due today at priority 1** and **broken promise at priority 2**. The §5.8 worked example shows `priority: 1, reason_code: "BROKEN_PROMISE"` and `priority: 2, reason_code: "PROMISE_DUE_TODAY"`.

**The PRD and the test case agree with each other and outrank a worked example.** Build to REQ-COL-008: 1 promise due today, 2 broken promise, 3 scheduled next call, 4 status changed alert, 5 mid overdue 8–29, 6 early overdue 1–7. Reuse the example's `reason_code` strings (`PROMISE_DUE_TODAY`, `BROKEN_PROMISE`), just not its numbering.

### 12.5 Today List response: `groups` or `items`?

The §4.3 table says the response holds `groups`. The §5.8 worked example returns `items` inside the standard page envelope with `page` and `meta`. **Build the example**: `items` is what makes cursor pagination and `fields=` selection coherent, and §2.6 says the envelope member is `items` on every list endpoint. Keep the `run` object alongside, and keep `meta.counts_by_priority`.

### 12.6 `stakeholder_type: "BORROWER"` in the worked example is not a legal value

The §5.2 example body sends `"stakeholder_type": "BORROWER"`. The enum in the PRD (REQ-COL-017), TC-COL-041 and `Event_Contracts.md` §4.3 is `PRIMARY_BORROWER, CO_BORROWER, GUARANTOR, THIRD_PARTY, ESTATE`. Request-side enums are **closed** (§2.1: "an unknown value is 422"), so the example as written would 422. **Use `PRIMARY_BORROWER`.**

### 12.7 Open issues the spec itself carries into the board and the KPIs

| Item | Status in the spec | Owner |
|---|---|---|
| `ptp_kept_partial_weight` and `ptp_partial_threshold_percent` unset → indicators 4 and 5 cannot be computed | VERIFY — "the arithmetic is fixed, only the constant is missing" | Debt Manager |
| Indicator 14 says "population" without stating count or amount; the snapshot stores **both** and labels the headline | VERIFY | Owner with Debt Manager |
| Indicator 7 has a definition but **no formula** in the spec; `1 − slid ÷ open-at-both-ends` is "an engineering reading, not a spec quote" | VERIFY | Debt Manager |
| Indicator 2's denominator — "the 40-item denominator is the Today List item count, **which the spec does not state explicitly**" | VERIFY | Debt Manager |
| Whether retroactive DPD is applied when service-issue abuse is found — recorded but **not enforced** | Open (D6) | — |
| Whether a KEPT restructure returns lifecycle to ACTIVE or stays RESTRUCTURED | Default: stays RESTRUCTURED | Debt Manager with Whan |
| SOP column 4's "cause A/B/C/D" letters are **deliberately not lettered A–D** in the dictionary, to avoid collision with the §11a.3 recovery paths | VERIFY | Debt Manager |
| Integration host naming: Odoo/PEAK docs print `api.<env>.debt.volt.co.th`; GCP_Architecture fixes one host per environment with path routing, and API_Surface follows GCP_Architecture | Open issue OI-API-01 | — |
| Role vocabulary reconciliation (CREDIT_RISK_MANAGER, COO, CEO seeded as separate roles) | Open issue OI-API-04 | — |

---

## 13. Build checklist for the prototype

Ordered by how expensive each is to retrofit.

1. **Mount at `/v1`.** Colon-suffix custom actions. Plural kebab-case paths. `uid` as the only path parameter.
2. **Money as strings with exactly two decimals.** Never floats, ever, anywhere. No `currency` field.
3. **`dpd: null` versus `dpd: 0` are different facts.** Model the field as nullable from day one.
4. **Cursor pagination only.** `items` / `page` / `meta` envelope on every list. No offsets. Every sort ends with `uid`.
5. **The daily lock is a unique partial index on `(lock_date, identity_hash)`**, not application logic — that is what makes the concurrent case correct.
6. **A refused contact writes nothing.** The 409 is audited as `col.contact.log` outcome BLOCKED; the row is never created.
7. **Two lock rows per counting contact** (PERSON and CONTRACT), always, even when only one level is enforced.
8. **Bangkok calendar day** for every lock, ledger and run date. Never the server default and never UTC.
9. **`counted` is computed by the server guard.** The client never sends it and never infers it.
10. **Every problem response carries `code`, `error_id`, `message_th`, `errors: []`, `extensions: {}`** — the last two present-and-empty rather than absent.
11. **`Idempotency-Key` on every contact, PTP, arrangement, hold, claim, money row and job start.**
12. **`If-Match` on every mutable-resource mutation**; 428 when missing, 412 on mismatch. Contacts are append-only and exempt.
13. **202 + `Location: /v1/jobs/{uid}` + `Retry-After`** for penalty bill, exception retry, reconcile run, document generation and every export. A failed job is a 200 poll with an `error` object.
14. **One query behind the exception dashboard and its alert.** Build it as a single named function from the start.
15. **Recovery paths as rows in a set**, opened and closed with reason and timestamp, never a status column, never deleted.
16. **Unset config → null plus a banner naming the key and its owner.** Never a default.
17. **Scope as a query predicate, never a post-filter**; out-of-scope on contracts, customers and documents answers **404**, not 403.
18. **Mask by default**; full identity or account numbers only through a `:reveal` endpoint with a mandatory `reason` and an audit row.

