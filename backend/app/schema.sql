-- Volt Debt staging schema. Two schemas, five tables.
--
-- landing holds ingested source data shaped like the New Order Master sheet.
-- app holds durable per-account state plus legacy browser-session rows retained for
-- rollback/backfill.
--
-- Every statement is IF NOT EXISTS: debt-migrate runs on every deploy.

CREATE SCHEMA IF NOT EXISTS landing;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS landing.import_run (
    id                bigserial PRIMARY KEY,
    source_system     text        NOT NULL CHECK (source_system IN ('SHEET','ODOO')),
    spreadsheet_id    text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'RUNNING'
                                  CHECK (status IN ('RUNNING','OK','FAILED')),
    row_counts        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    reconciled        boolean,
    truncated_blocks  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    note              text
);

-- The successful runs, newest first, are the only ones book_source reads.
CREATE INDEX IF NOT EXISTS import_run_ok_idx
    ON landing.import_run (source_system, id DESC) WHERE status = 'OK';

-- data_source sits INSIDE the primary key on purpose: a SHEET row and an ODOO row
-- for the same volt_id must coexist, or the overlay cannot be expressed at all.
CREATE TABLE IF NOT EXISTS landing.customer (
    volt_id         text NOT NULL,
    data_source     text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    customer_no     text,
    name_roman      text,
    name_th         text,
    epc             text,
    product         text,
    sales_lead      text,
    phone_masked    text,
    phone_e164      text,
    email_masked    text,
    line_id         text,
    meta_id         text,
    source_refs     jsonb  NOT NULL DEFAULT '[]'::jsonb,
    import_run_id   bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, data_source)
);

ALTER TABLE landing.customer ADD COLUMN IF NOT EXISTS line_id text;
ALTER TABLE landing.customer ADD COLUMN IF NOT EXISTS meta_id text;

CREATE TABLE IF NOT EXISTS landing."order" (
    volt_id               text NOT NULL,
    data_source           text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    no                    integer,
    crm_id                text,
    order_type            text,
    order_status          text,
    loan_status           text,
    submit_date           date,
    contract_signed_date  date,
    epc_start_date        date,
    epc_end_date          date,
    amount_total          numeric,
    source_ref            jsonb  NOT NULL DEFAULT '[]'::jsonb,
    import_run_id         bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, data_source)
);

-- Odoo writes ZERO rows here. sale.order and res.partner contain nothing that
-- answers leasing or tracking; the schema states that boundary rather than
-- hiding it behind columns full of NULL.
CREATE TABLE IF NOT EXISTS landing.customer_block (
    volt_id        text NOT NULL,
    block          text NOT NULL CHECK (block IN
                        ('leasing','tracking','cash','cash_invoices','asset','contact_log')),
    data_source    text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    payload        jsonb  NOT NULL,
    import_run_id  bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, block, data_source)
);

-- Unmapped vocabulary values, one row per (run, volt, field, value). They used to
-- live in import_run.meta, and at 350k leads the 700k entries decoded to ~400 MB of
-- Python on EVERY read of the run row — and the run row is read at boot. A table
-- keeps the receipt's sample and the per-volt view exact without that decode.
CREATE TABLE IF NOT EXISTS landing.import_unmapped (
    import_run_id bigint NOT NULL REFERENCES landing.import_run(id),
    volt_id       text   NOT NULL,
    field         text   NOT NULL,
    value         text   NOT NULL,
    PRIMARY KEY (import_run_id, volt_id, field, value)
);

CREATE TABLE IF NOT EXISTS app.session_state (
    session_id    text NOT NULL,
    key           text NOT NULL,
    payload       bytea      NOT NULL,
    codec         text       NOT NULL DEFAULT 'pickle-v1',
    code_version  text       NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, key)
);

CREATE INDEX IF NOT EXISTS session_state_updated_idx
    ON app.session_state (updated_at);

-- Durable work belongs to an authenticated account, not to a 12-hour browser
-- cookie and not to a Cloud Run revision. app.session_state remains untouched as
-- the rollback source for pre-migration browsers.
CREATE TABLE IF NOT EXISTS app.user_state (
    principal_key text        NOT NULL,
    key           text        NOT NULL,
    payload       bytea       NOT NULL,
    codec         text        NOT NULL DEFAULT 'pickle-v1',
    schema_version integer    NOT NULL DEFAULT 2,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (principal_key, key)
);

CREATE INDEX IF NOT EXISTS user_state_updated_idx
    ON app.user_state (updated_at);

-- One-time authorisation for the eligibility cleanup. The token survives a Cloud
-- Run revision change so staging can preview on the old revision and apply only
-- those exact counts after the new revision is deployed.
CREATE TABLE IF NOT EXISTS app.crm_eligibility_preview (
    token          text        PRIMARY KEY,
    principal_key  text        NOT NULL,
    expected       jsonb       NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),
    applied_at     timestamptz,
    apply_run_id   bigint      REFERENCES landing.import_run(id)
);

CREATE INDEX IF NOT EXISTS crm_eligibility_preview_owner_idx
    ON app.crm_eligibility_preview (principal_key, created_at DESC);

CREATE TABLE IF NOT EXISTS app.user_state_archive (
    id             bigserial   PRIMARY KEY,
    principal_key  text,
    session_id     text        NOT NULL,
    key            text        NOT NULL,
    payload        bytea       NOT NULL,
    codec          text        NOT NULL,
    code_version   text,
    source_updated_at timestamptz NOT NULL,
    archived_at    timestamptz NOT NULL DEFAULT now(),
    reason         text        NOT NULL,
    UNIQUE (session_id, key, source_updated_at, reason)
);

-- The import epoch (2026-09-20 sync audit): one monotone row per act that makes
-- imported facts different from what a session last seeded from. It is how a
-- session that did NOT press Apply learns it is behind — the per-request check in
-- app/import_sync.py compares max(id) with the session's own seen value. `kind`
-- names the door ("crm-lead", "peak", "odoo", "upload"); `run_id` points at the
-- landing run where one exists, so a heal can name what it is catching up to.
CREATE TABLE IF NOT EXISTS app.data_epoch (
    id      bigserial   PRIMARY KEY,
    kind    text        NOT NULL,
    run_id  bigint,
    at      timestamptz NOT NULL DEFAULT now()
);

-- Added after the first end-to-end run, which found two kinds of loss.
--
-- landing."order".extra: the sheet's order block carries thirteen fields the
-- normalised columns do not (dp_amount, dp_pct, epc, term, watt, monthly_rate,
-- project_type, province, odoo_id, peak_id, the masked contacts). Dropping them
-- made the invoice pipeline return 500, because the down-payment gate reads
-- dp_amount. Normalise the overlap, JSONB the rest — the same rule the customer
-- blocks already follow.
--
-- landing.import_run.meta: pivots, flow_stages and warnings are properties of the
-- IMPORT, not of any row, so they belong on the run. Without them the migration
-- report could not reconcile and could not say why.
ALTER TABLE landing."order"      ADD COLUMN IF NOT EXISTS extra jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE landing.import_run   ADD COLUMN IF NOT EXISTS meta  jsonb NOT NULL DEFAULT '{}'::jsonb;

-- The crm.lead door's newest run (landing.last_lead_run). Without it the query was a
-- seq scan that had to decode every run's meta — one 2026-09-20 run carried 3.1 MB —
-- and /last-run cost 425 ms per call (Data sources mount, sync audit).
CREATE INDEX IF NOT EXISTS import_run_lead_idx
    ON landing.import_run (id DESC)
    WHERE source_system = 'ODOO' AND meta ? 'door';


-- The action audit log (design 2026-09-11) lives in its OWN schema, not app,
-- and not by accident. Schema `app` holds mutable application records whose
-- lifecycle differs from the append-only audit chain. This table is the one thing
-- that must NEVER be discarded. Putting an append-only, never-cleaned table in
-- the same schema as a table that every test harness truncates on principle
-- was the mistake (see tests/conftest.py's pg_conn fixture, which truncates
-- every table in schemas landing and app between tests) — the schema boundary
-- now expresses the difference in lifetime instead of relying on everyone
-- remembering to special-case one table.
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.entry (
    seq             bigserial PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    business_date   date        NOT NULL,
    actor_claimed   text,
    actor_source    text        NOT NULL CHECK (actor_source IN ('HEADER','BODY','NONE','SESSION','TEST_ACCOUNT')),
    session_id      text,
    request_id      text,
    verb            text        NOT NULL,
    route_template  text        NOT NULL,
    act             text,
    subject_type    text,
    subject_uid     text,
    detail          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    outcome         text        NOT NULL CHECK (outcome IN ('OK','REFUSED')),
    status          int         NOT NULL,
    error_code      text,
    prev_hash       text        NOT NULL,
    hash            text        NOT NULL
);

-- Login (design 2026-09-13): a database made before login exists still carries the
-- three-value check, and CREATE TABLE IF NOT EXISTS will not touch it. Dropped and
-- re-added by name so every deploy converges on the same constraint. Postgres named
-- the inline check entry_actor_source_check. A row trigger does not block ALTER TABLE.
ALTER TABLE audit.entry DROP CONSTRAINT IF EXISTS entry_actor_source_check;
ALTER TABLE audit.entry ADD CONSTRAINT entry_actor_source_check
    CHECK (actor_source IN ('HEADER','BODY','NONE','SESSION','TEST_ACCOUNT'));

-- R13: the signing role. NULL on every row written before it existed (and on a request
-- with no session and no known X-Volt-Role); audit.hash_entry leaves a NULL out of the
-- hash, so those rows still verify. ADD COLUMN does not fire the row trigger.
ALTER TABLE audit.entry ADD COLUMN IF NOT EXISTS actor_role text;
ALTER TABLE audit.entry DROP CONSTRAINT IF EXISTS entry_actor_role_check;
ALTER TABLE audit.entry ADD CONSTRAINT entry_actor_role_check
    CHECK (actor_role IS NULL OR actor_role IN ('OFFICER','SUPERVISOR','MANAGER','OWNER','OPS'));

CREATE INDEX IF NOT EXISTS entry_at_idx      ON audit.entry (at DESC);
CREATE INDEX IF NOT EXISTS entry_actor_idx   ON audit.entry (actor_claimed);
CREATE INDEX IF NOT EXISTS entry_subject_idx ON audit.entry (subject_type, subject_uid);

-- One-time/idempotent browser-state backfill. Audit is the only trustworthy bridge
-- from an old browser session id to the account that used it. For each account and
-- Store key, the newest row wins. Older mapped rows are archived; every original
-- app.session_state row (including unmapped rows) remains in place for rollback.
WITH mapped AS (
    SELECT ss.*,
           'user:' || lower(trim(identity.actor_claimed)) AS principal_key
    FROM app.session_state ss
    JOIN LATERAL (
        SELECT e.actor_claimed
        FROM audit.entry e
        WHERE e.session_id = ss.session_id
          AND e.actor_claimed IS NOT NULL
          AND e.actor_source IN ('SESSION', 'TEST_ACCOUNT')
        ORDER BY e.at DESC, e.seq DESC
        LIMIT 1
    ) identity ON true
), ranked AS (
    SELECT mapped.*,
           row_number() OVER (
               PARTITION BY principal_key, key
               ORDER BY updated_at DESC, session_id DESC
           ) AS choice
    FROM mapped
)
INSERT INTO app.user_state (principal_key, key, payload, codec, schema_version, updated_at)
SELECT principal_key, key, payload, codec, 1, updated_at
FROM ranked
WHERE choice = 1
ON CONFLICT (principal_key, key) DO NOTHING;

WITH mapped AS (
    SELECT ss.*,
           'user:' || lower(trim(identity.actor_claimed)) AS principal_key
    FROM app.session_state ss
    JOIN LATERAL (
        SELECT e.actor_claimed
        FROM audit.entry e
        WHERE e.session_id = ss.session_id
          AND e.actor_claimed IS NOT NULL
          AND e.actor_source IN ('SESSION', 'TEST_ACCOUNT')
        ORDER BY e.at DESC, e.seq DESC
        LIMIT 1
    ) identity ON true
), ranked AS (
    SELECT mapped.*,
           row_number() OVER (
               PARTITION BY principal_key, key
               ORDER BY updated_at DESC, session_id DESC
           ) AS choice
    FROM mapped
)
INSERT INTO app.user_state_archive
    (principal_key, session_id, key, payload, codec, code_version,
     source_updated_at, reason)
SELECT principal_key, session_id, key, payload, codec, code_version,
       updated_at, 'older_session_for_principal'
FROM ranked
WHERE choice > 1
ON CONFLICT (session_id, key, source_updated_at, reason) DO NOTHING;

-- Append-only, enforced by the database rather than by everyone remembering.
-- A GRANT would not do it: the application connects as the owner, and an owner is
-- not bound by its own grants. A trigger binds everyone, including a bug.
CREATE OR REPLACE FUNCTION audit.entry_is_append_only() RETURNS trigger AS $guard$
BEGIN
    RAISE EXCEPTION 'audit.entry is append-only: % is refused', TG_OP;
END;
$guard$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS entry_no_change ON audit.entry;
CREATE TRIGGER entry_no_change
    BEFORE UPDATE OR DELETE ON audit.entry
    FOR EACH ROW EXECUTE FUNCTION audit.entry_is_append_only();

-- A row-level trigger (above) does not fire on TRUNCATE at all — Postgres treats
-- TRUNCATE as a separate statement-level event, not N row deletes. And an empty
-- chain verifies clean: audit.Chain.verify() on zero entries reports ok=True,
-- complete=True. So without a second, statement-level guard, TRUNCATE is the one
-- tamper this design cannot see: it erases the whole log, is permitted by the
-- row trigger above, and leaves verify() reporting nothing wrong — worse than the
-- single-row edit the chain was built to catch. This guard closes that hole.
CREATE OR REPLACE FUNCTION audit.entry_no_truncate() RETURNS trigger AS $guard$
BEGIN
    RAISE EXCEPTION 'audit.entry is append-only: TRUNCATE is refused';
END;
$guard$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS entry_no_truncate ON audit.entry;
CREATE TRIGGER entry_no_truncate
    BEFORE TRUNCATE ON audit.entry
    FOR EACH STATEMENT EXECUTE FUNCTION audit.entry_no_truncate();

-- Feedback Round 1 / WP1 (vault note 10 §3, F4). The PEAK invoice report lands
-- beside the sheet and Odoo under its own source. Postgres named the inline check
-- import_run_source_system_check; dropped and re-added by name so an existing
-- database converges (the audit block above does the same for actor_source).
ALTER TABLE landing.import_run DROP CONSTRAINT IF EXISTS import_run_source_system_check;
ALTER TABLE landing.import_run ADD CONSTRAINT import_run_source_system_check
    CHECK (source_system IN ('SHEET','ODOO','PEAK','PEAK_RECEIPT'));

-- Feedback round 2 / Q6 (TASK-202): the receipt export ("รายงานใบเสร็จรับเงิน") lands
-- in its own table — the frequent upload, one row per receipt with its lines folded
-- into jsonb, run-scoped like every landing row. The 13-digit id is NOT a column
-- here (F5/PDPA). invoice_doc_no is the invoice this receipt settles (the อ้างอิง it
-- matched); customer_no is the customer the run served it to.
CREATE TABLE IF NOT EXISTS landing.peak_receipt (
    import_run_id   bigint  NOT NULL REFERENCES landing.import_run(id),
    doc_no          text    NOT NULL,
    doc_kind        text    NOT NULL,
    issued_on       date,
    invoice_ref     text,
    contact_code    text,
    customer_name   text,
    status          text    NOT NULL CHECK (status IN ('PAID','DRAFT','CANCELLED')),
    cycle_n         int,
    cycle_of        int,
    amount_total    numeric(14,2),
    amount_due      numeric(14,2),
    paid_on         date,
    paid_channel    text,
    paid_amount     numeric(14,2),
    note            text,
    lines           jsonb   NOT NULL DEFAULT '[]'::jsonb,
    verdict         text    NOT NULL CHECK (verdict IN ('EXACT','CANDIDATE','UNMATCHED','REJECTED')),
    rule            text,
    customer_no     text,
    invoice_doc_no  text,
    candidates      jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (import_run_id, doc_no)
);
CREATE INDEX IF NOT EXISTS peak_receipt_ref_idx     ON landing.peak_receipt (invoice_ref);
CREATE INDEX IF NOT EXISTS peak_receipt_contact_idx ON landing.peak_receipt (contact_code);
CREATE INDEX IF NOT EXISTS peak_receipt_run_idx     ON landing.peak_receipt (import_run_id);

-- One row per PEAK invoice (lines folded into jsonb), run-scoped like every landing
-- row. The 13-digit id on the report is NOT a column here, by ruling F5.
CREATE TABLE IF NOT EXISTS landing.peak_invoice (
    import_run_id    bigint  NOT NULL REFERENCES landing.import_run(id),
    doc_no           text    NOT NULL,
    doc_kind         text    NOT NULL,
    issued_on        date,
    due_on           date,
    reference        text,
    system_reference text,
    contact_code     text,
    customer_name    text,
    status           text    NOT NULL CHECK (status IN ('PAID','OVERDUE','AWAITING','DRAFT','CANCELLED')),
    cycle_n          int,
    cycle_of         int,
    product_group    text,
    amount_total     numeric(14,2),
    amount_due       numeric(14,2),
    amount_awaiting  numeric(14,2),
    paid_on          date,
    paid_channel     text,
    paid_amount      numeric(14,2),
    receipt_no       text,
    note             text,
    lines            jsonb   NOT NULL DEFAULT '[]'::jsonb,
    verdict          text    NOT NULL CHECK (verdict IN ('EXACT','CANDIDATE','UNMATCHED','REJECTED')),
    rule             text,
    customer_no      text,
    candidates       jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (import_run_id, doc_no)
);
-- PEAK includes cancelled invoice observations in annual exports. Keep them in the
-- staged run for traceability; book reads filter them out with drafts.
ALTER TABLE landing.peak_invoice DROP CONSTRAINT IF EXISTS peak_invoice_status_check;
ALTER TABLE landing.peak_invoice ADD CONSTRAINT peak_invoice_status_check
    CHECK (status IN ('PAID','OVERDUE','AWAITING','DRAFT','CANCELLED'));
-- Final review C1: the ladder's own verdict WITHOUT the link register, per row, so the
-- book's read can let the register decide at read time — an active link serves the
-- row to its customer; with no active link, only the ladder's own EXACT does. NULL on
-- a row landed before these columns existed (read by its stored verdict, never LINK).
ALTER TABLE landing.peak_invoice ADD COLUMN IF NOT EXISTS ladder_verdict     text;
ALTER TABLE landing.peak_invoice ADD COLUMN IF NOT EXISTS ladder_customer_no text;
ALTER TABLE landing.peak_invoice ADD COLUMN IF NOT EXISTS ladder_rule        text;
-- Feedback round 2 / Q7 (TASK-208): the fields where PEAK and the Odoo record
-- disagree, on EXACT rows only; NULL when they agree or a field is not comparable.
ALTER TABLE landing.peak_invoice ADD COLUMN IF NOT EXISTS conflicts          jsonb;
CREATE INDEX IF NOT EXISTS peak_invoice_customer_idx ON landing.peak_invoice (customer_no);
CREATE INDEX IF NOT EXISTS peak_invoice_contact_idx  ON landing.peak_invoice (contact_code);
CREATE INDEX IF NOT EXISTS peak_invoice_run_idx      ON landing.peak_invoice (import_run_id);

-- Schema records: the product's memory. Not app (per-tester, discarded on deploy,
-- truncated by the test harness on principle) and not audit (append-only).
CREATE SCHEMA IF NOT EXISTS records;

CREATE TABLE IF NOT EXISTS records.message_template (
    uid         text        PRIMARY KEY,
    owner       text        NOT NULL,
    channel     text        NOT NULL CHECK (channel IN ('LINE','FACEBOOK')),
    name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    body        text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS message_template_owner_channel_idx
    ON records.message_template (owner, channel, updated_at DESC);

CREATE TABLE IF NOT EXISTS records.identity_link (
    uid           bigserial   PRIMARY KEY,
    contact_code  text        NOT NULL,
    customer_no   text        NOT NULL,
    contract_uid  text,
    rule          text        NOT NULL,
    confirmed_by  text        NOT NULL,
    confirmed_at  timestamptz NOT NULL DEFAULT now(),
    reason        text,
    retired_at    timestamptz,
    retired_by    text,
    -- 2026-10-01: two registers share this table. PEAK_LINK rows are what a person
    -- confirmed about a PEAK contact code (rung 0 of the identity ladder); the
    -- ODOO_CRM_LEAD rows are the automatic link a crm.lead pull leaves behind for
    -- every lead the SHEET book already holds, so the case can still deep-link to
    -- the Odoo lead after the merged ODOO landing row retires.
    source        text        NOT NULL DEFAULT 'PEAK_LINK',
    odoo_lead_id  bigint
);
-- Columns for databases created before 2026-10-01.
ALTER TABLE records.identity_link ADD COLUMN IF NOT EXISTS source       text NOT NULL DEFAULT 'PEAK_LINK';
ALTER TABLE records.identity_link ADD COLUMN IF NOT EXISTS odoo_lead_id bigint;
-- One ACTIVE link per (source, contact code); a retired one stays as history. The
-- source is in the key because an Odoo volt_id and a PEAK contact code can be the
-- same string ("VL0000143") without being the same claim.
DROP INDEX IF EXISTS records.identity_link_active_idx;
CREATE UNIQUE INDEX IF NOT EXISTS identity_link_active_idx
    ON records.identity_link (source, contact_code) WHERE retired_at IS NULL;
-- The book's Odoo-link read: active Odoo links for the served customer numbers.
CREATE INDEX IF NOT EXISTS identity_link_odoo_customer_idx
    ON records.identity_link (customer_no)
    WHERE retired_at IS NULL AND source = 'ODOO_CRM_LEAD';
-- The book's invoice read matches link codes against PEAK contact codes with all
-- whitespace stripped and case folded; this indexes the link side of that join on
-- the SAME expression, so it can stop sorting the whole register per invoice.
CREATE INDEX IF NOT EXISTS identity_link_contact_norm_idx
    ON records.identity_link (upper(regexp_replace(coalesce(contact_code, ''), '[[:space:]]+', '', 'g')))
    WHERE retired_at IS NULL;

-- Feedback Round 1 / WP4 (design F7): evidence files on a contact or a note. Bytes
-- live here, never on disk; INFECTED is never a stored state — such a file is refused
-- at upload. attached_to is "contact:<uid>" | "note:<uid>" | NULL while pending.
CREATE TABLE IF NOT EXISTS records.attachment (
    uid           text        PRIMARY KEY,
    sha256        text        NOT NULL,
    kind          text        NOT NULL CHECK (kind IN ('PNG','SVG','CSV','XLSX','DOCX','PDF')),
    content_type  text        NOT NULL,
    size          int         NOT NULL,
    filename      text        NOT NULL,
    uploaded_by   text        NOT NULL,
    uploaded_at   timestamptz NOT NULL DEFAULT now(),
    scan_state    text        NOT NULL CHECK (scan_state IN ('CLEAN','RULES_ONLY')),
    scan_by       text        NOT NULL,
    attached_to   text,
    deleted_at    timestamptz,
    deleted_by    text,
    bytes         bytea       NOT NULL
);
CREATE INDEX IF NOT EXISTS attachment_target_idx ON records.attachment (attached_to) WHERE deleted_at IS NULL;

-- Feedback Round 1 / WP10 (design F13, F14): the allow-list people manage, merged over
-- the AUTH_ALLOWLIST seed, and each person's own display name. GOOGLE rows are keyed by
-- the lower-cased e-mail; TEST rows by the test-account username and carry only a
-- display name (password test accounts are unchanged). No row is ever deleted: a set
-- disabled_at refuses sign-in whatever the seed says.
CREATE TABLE IF NOT EXISTS records.user_account (
    id            bigserial   PRIMARY KEY,
    kind          text        NOT NULL CHECK (kind IN ('GOOGLE','TEST')),
    email         text,
    username      text,
    role          text        CHECK (role IN ('OFFICER','SUPERVISOR','MANAGER','OWNER','OPS')),
    officer       text,
    display_name  text,
    invited_by    text,
    invited_at    timestamptz,
    disabled_at   timestamptz,
    disabled_by   text,
    CONSTRAINT user_account_key_check CHECK (
        (kind = 'GOOGLE' AND email IS NOT NULL AND username IS NULL AND email = lower(email))
        OR (kind = 'TEST' AND username IS NOT NULL AND email IS NULL AND role IS NULL)),
    CONSTRAINT user_account_role_needs_officer CHECK (role IS NULL OR officer IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS user_account_email_idx    ON records.user_account (email)    WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_account_username_idx ON records.user_account (username) WHERE username IS NOT NULL;

-- Feedback Round 1 / WP9 (design F9 (a)): a phone number a person entered for a
-- customer, with who, when and why. PDPA: the only table that holds one — never an
-- audit detail, a log line or an export. Every set or clear is a new row; the one
-- ACTIVE row per customer is the number served. A clear is a row with no number and
-- active = false, so the history keeps who removed it and why.
CREATE TABLE IF NOT EXISTS records.customer_contact (
    uid           bigserial   PRIMARY KEY,
    customer_uid  text        NOT NULL,
    phone_e164    text        CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+66[0-9]{8,9}$'),
    kind          text        CHECK (kind IS NULL OR kind IN ('MOBILE','LANDLINE')),
    set_by        text        NOT NULL,
    set_at        timestamptz NOT NULL DEFAULT now(),
    reason        text        NOT NULL,
    active        boolean     NOT NULL DEFAULT true,
    CHECK (NOT active OR phone_e164 IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS customer_contact_active_idx
    ON records.customer_contact (customer_uid) WHERE active;

-- Feedback Round 1 / WP6 (design F16): personal notices on the calendar. One owner each,
-- no sharing, no recurrence, no e-mail. Soft-deleted so the NOTICE_DELETED audit row
-- still points at a row. "on" and "time" are SQL words, hence on_date and at_time.
CREATE TABLE IF NOT EXISTS records.notice (
    uid           text        PRIMARY KEY,
    owner         text        NOT NULL,
    title         text        NOT NULL,
    on_date       date        NOT NULL,
    at_time       time,
    customer_uid  text,
    note_text     text,
    done          boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz,
    deleted_by    text
);
CREATE INDEX IF NOT EXISTS notice_owner_on_idx ON records.notice (owner, on_date) WHERE deleted_at IS NULL;


-- Feedback round 2 / Q7 (TASK-207): a person's field decision on the Debt platform's
-- served record, with provenance. Nothing is written back to Odoo; the active row is
-- the one with retired_at IS NULL, and retiring it restores the Odoo value.
CREATE TABLE IF NOT EXISTS records.field_decision (
    uid            bigserial   PRIMARY KEY,
    customer_no    text        NOT NULL,
    field          text        NOT NULL,
    chosen_source  text        NOT NULL CHECK (chosen_source IN ('PEAK','ODOO')),
    peak_value     text,
    odoo_value     text,
    decided_by     text        NOT NULL,
    decided_at     timestamptz NOT NULL DEFAULT now(),
    reason         text,
    run_id         bigint      REFERENCES landing.import_run(id),
    retired_at     timestamptz,
    retired_by     text
);
CREATE UNIQUE INDEX IF NOT EXISTS field_decision_active_idx
    ON records.field_decision (customer_no, field) WHERE retired_at IS NULL;


-- PEAK webhooks, Stage A (app/peak_webhooks.py): every event PEAK sends, kept as bytes
-- before anything reads it. 13-digit runs are masked before insert (F5/PDPA). A body
-- sent twice is one row.
CREATE TABLE IF NOT EXISTS landing.peak_webhook_event (
    id            bigserial   PRIMARY KEY,
    kind          text        NOT NULL CHECK (kind IN ('contact','invoice','receipt')),
    body_sha256   text        NOT NULL,
    body          bytea       NOT NULL,
    content_type  text,
    received_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, body_sha256)
);


-- Fix-all round (2026-09-25), Step 0: the seams the legs build on.
-- A landed row that a later complete pull or sheet install no longer carries is
-- RETIRED, not deleted: every book read skips it, and landing it again clears it.
ALTER TABLE landing.customer       ADD COLUMN IF NOT EXISTS retired_at timestamptz;
ALTER TABLE landing."order"        ADD COLUMN IF NOT EXISTS retired_at timestamptz;
ALTER TABLE landing.customer_block ADD COLUMN IF NOT EXISTS retired_at timestamptz;

-- Leg O (2026-09-25): the crm.lead pull's change-detection digest (sha256 of the
-- normalised lead) lives in its own column, never in the served `extra`: every
-- input of the hash but the full phone number is served, so a served digest gives
-- the number back to a 10^4 brute force.
ALTER TABLE landing."order"        ADD COLUMN IF NOT EXISTS row_digest text;
-- Rows landed by the first cut of that pull kept the digest in `extra`, which the
-- served book merges; drop it there. Idempotent: after one run it matches no row.
UPDATE landing."order" SET extra = extra - 'row_digest' WHERE extra ? 'row_digest';

-- A webhook body over the size cap is kept truncated rather than refused (PEAK never
-- retries a refused event), and says so.
ALTER TABLE landing.peak_webhook_event ADD COLUMN IF NOT EXISTS truncated  boolean NOT NULL DEFAULT false;
ALTER TABLE landing.peak_webhook_event ADD COLUMN IF NOT EXISTS size_bytes integer;

-- A manager's manual payment status, shared by every session (Arina, 2026-09-24).
-- The active row is the one with retired_at IS NULL; it applies while the system's
-- own answer is still the one it overruled (system_code_at_set).
CREATE TABLE IF NOT EXISTS records.payment_status_override (
    uid                 bigserial   PRIMARY KEY,
    customer_uid        text        NOT NULL,
    code                text        NOT NULL,
    system_code_at_set  text,
    reason              text,
    set_by              text        NOT NULL,
    set_at              timestamptz NOT NULL DEFAULT now(),
    retired_at          timestamptz,
    retired_by          text
);
CREATE UNIQUE INDEX IF NOT EXISTS payment_status_override_active_idx
    ON records.payment_status_override (customer_uid) WHERE retired_at IS NULL;

-- Monthly history (Arina, 2026-09-25): one row per customer per month. The current
-- month's row follows every landing (monthly_history.snapshot); a month that has
-- turned is never written again — the app only ever writes the current month's key.
CREATE TABLE IF NOT EXISTS records.customer_month (
    month           char(7)       NOT NULL,          -- 'YYYY-MM', Bangkok business date
    customer_uid    text          NOT NULL,
    volt_id         text,
    customer_no     text,
    product         text,
    payment_status  text          NOT NULL,
    status_source   text          NOT NULL,          -- PEAK | SHEET | OVERRIDE | CONTRACT
    overdue         numeric(14,2),
    outstanding     numeric(14,2),
    oldest_dpd      integer,
    officer         text,
    taken_at        timestamptz   NOT NULL DEFAULT now(),
    taken_by_kind   text,                            -- sheet | peak | odoo | override | boot …
    PRIMARY KEY (month, customer_uid)
);
-- A customer who leaves the book mid-month keeps their row (records has no DELETE)
-- but is no longer counted in that month (review, 2026-09-25).
ALTER TABLE records.customer_month ADD COLUMN IF NOT EXISTS in_book boolean NOT NULL DEFAULT true;

-- Amount-led payment journey (2026-09-29). A claim is provisional and never edits
-- confirmed receivables. Receipt observations are immutable in landing; these
-- ledgers record how the latest valid observation was allocated and can be reversed
-- when PEAK later exports the same receipt as cancelled.
CREATE TABLE IF NOT EXISTS records.payment_claim (
    uid                 text          PRIMARY KEY,
    customer_uid        text          NOT NULL,
    amount              numeric(14,2) NOT NULL CHECK (amount > 0),
    paid_on             date          NOT NULL,
    reference           text,
    evidence_uid        text,
    note                text,
    created_by          text          NOT NULL,
    created_role        text          NOT NULL CHECK (created_role IN ('OFFICER','SUPERVISOR','MANAGER','OWNER')),
    created_at          timestamptz   NOT NULL DEFAULT now(),
    idempotency_key     text          NOT NULL,
    state               text          NOT NULL CHECK (state IN
        ('PENDING','CONFIRMED','PARTIALLY_CONFIRMED','NEEDS_REVIEW','CANCELLED')),
    confirmed_amount    numeric(14,2) NOT NULL DEFAULT 0 CHECK (confirmed_amount >= 0),
    credit_amount       numeric(14,2) NOT NULL DEFAULT 0 CHECK (credit_amount >= 0),
    resolution_run_id   bigint        REFERENCES landing.import_run(id),
    resolved_at         timestamptz,
    resolution_note     text,
    cancelled_by        text,
    cancelled_at        timestamptz
);
-- Idempotency belongs to one customer's command stream. A client-generated key
-- reused for another customer must neither collide nor reveal the other claim.
ALTER TABLE records.payment_claim
    DROP CONSTRAINT IF EXISTS payment_claim_idempotency_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS payment_claim_customer_idempotency_idx
    ON records.payment_claim (customer_uid, idempotency_key);
CREATE INDEX IF NOT EXISTS payment_claim_customer_state_idx
    ON records.payment_claim (customer_uid, state, created_at);
CREATE INDEX IF NOT EXISTS payment_claim_paid_on_idx
    ON records.payment_claim (paid_on) WHERE state = 'PENDING';

CREATE TABLE IF NOT EXISTS records.payment_claim_target (
    claim_uid          text          NOT NULL REFERENCES records.payment_claim(uid),
    invoice_doc_no     text          NOT NULL,
    invoice_uid        text,
    amount             numeric(14,2) NOT NULL CHECK (amount > 0),
    allocation_order   integer       NOT NULL CHECK (allocation_order > 0),
    before_amount      numeric(14,2) NOT NULL CHECK (before_amount >= 0),
    after_amount       numeric(14,2) NOT NULL CHECK (after_amount >= 0),
    PRIMARY KEY (claim_uid, allocation_order)
);
CREATE INDEX IF NOT EXISTS payment_claim_target_invoice_idx
    ON records.payment_claim_target (invoice_doc_no);

CREATE TABLE IF NOT EXISTS records.payment_allocation (
    receipt_doc_no     text          NOT NULL,
    allocation_key    text          NOT NULL,
    customer_uid       text          NOT NULL,
    customer_no        text,
    invoice_doc_no     text,
    claim_uid          text          REFERENCES records.payment_claim(uid),
    amount             numeric(14,2) NOT NULL CHECK (amount >= 0),
    allocation_order   integer       NOT NULL CHECK (allocation_order > 0),
    source_run_id      bigint        NOT NULL REFERENCES landing.import_run(id),
    before_amount      numeric(14,2) NOT NULL CHECK (before_amount >= 0),
    after_amount       numeric(14,2) NOT NULL CHECK (after_amount >= 0),
    active              boolean       NOT NULL DEFAULT true,
    reconciled_at       timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (receipt_doc_no, allocation_key)
);
CREATE INDEX IF NOT EXISTS payment_allocation_customer_idx
    ON records.payment_allocation (customer_uid, active);
CREATE INDEX IF NOT EXISTS payment_allocation_invoice_idx
    ON records.payment_allocation (invoice_doc_no, active);

CREATE TABLE IF NOT EXISTS records.payment_claim_receipt (
    claim_uid       text          NOT NULL REFERENCES records.payment_claim(uid),
    receipt_doc_no  text          NOT NULL,
    amount          numeric(14,2) NOT NULL CHECK (amount > 0),
    source_run_id   bigint        NOT NULL REFERENCES landing.import_run(id),
    matched_at      timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_uid, receipt_doc_no)
);

-- Receipts that cannot pass strict invoice + customer matching remain visible
-- after the apply request has finished. Reconciliation marks the previous set
-- resolved and reactivates only exceptions still present in the latest rebuild.
CREATE TABLE IF NOT EXISTS records.payment_reconciliation_exception (
    exception_key    text        PRIMARY KEY,
    kind             text        NOT NULL CHECK (kind IN ('RECEIPT')),
    receipt_doc_no   text,
    customer_uid     text,
    invoice_doc_no   text,
    reason           text        NOT NULL,
    source_run_id    bigint      REFERENCES landing.import_run(id),
    detail           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    active           boolean     NOT NULL DEFAULT true,
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at      timestamptz
);
CREATE INDEX IF NOT EXISTS payment_reconciliation_exception_active_idx
    ON records.payment_reconciliation_exception (active, last_seen_at DESC);

-- One consolidated reminder per customer and Bangkok calendar month.
CREATE TABLE IF NOT EXISTS records.payment_reminder (
    customer_uid  text        NOT NULL,
    month         char(7)     NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    payload       jsonb       NOT NULL,
    sent_by       text        NOT NULL,
    sent_at       timestamptz NOT NULL DEFAULT now(),
    channel       text,
    PRIMARY KEY (customer_uid, month)
);
CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.auth_session (
    token_hash text PRIMARY KEY CHECK (length(token_hash) = 64),
    subject text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS auth_session_subject_idx ON app.auth_session(subject) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS app.business_record (
    store_key text NOT NULL, record_key text NOT NULL, payload jsonb NOT NULL,
    schema_version integer NOT NULL DEFAULT 1, version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(store_key,record_key)
);
CREATE TABLE IF NOT EXISTS app.schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), version integer NOT NULL
);
INSERT INTO app.schema_version(singleton,version) VALUES(true,1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS app.business_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), version bigint NOT NULL DEFAULT 0
);
INSERT INTO app.business_version(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS app.request_result (
    subject text NOT NULL, key text NOT NULL, fingerprint text NOT NULL,
    status integer NOT NULL, headers jsonb NOT NULL, body bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(subject,key)
);
CREATE TABLE IF NOT EXISTS app.operation_run (
    uid text PRIMARY KEY, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.task_outbox (
    uid text PRIMARY KEY REFERENCES app.operation_run(uid), payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), dispatched_at timestamptz, finished_at timestamptz
);
ALTER TABLE app.task_outbox ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0;
ALTER TABLE app.task_outbox ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz;
CREATE TABLE IF NOT EXISTS app.upload_session (
    upload_id text PRIMARY KEY, owner text NOT NULL, parts integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), consumed_at timestamptz
);
CREATE TABLE IF NOT EXISTS app.upload_part (
    upload_id text REFERENCES app.upload_session(upload_id), part_index integer NOT NULL,
    object_name text NOT NULL, size integer NOT NULL, PRIMARY KEY(upload_id,part_index)
);
-- Shared service-fault adjustments survive import reseeding and browser sessions.
CREATE TABLE IF NOT EXISTS records.service_deferral (
    uid text PRIMARY KEY,
    payload jsonb NOT NULL
);
ALTER TABLE records.attachment ADD COLUMN IF NOT EXISTS object_name text;
ALTER TABLE records.attachment ALTER COLUMN bytes DROP NOT NULL;
CREATE TABLE IF NOT EXISTS app.schedule_config (
    name text PRIMARY KEY, enabled boolean NOT NULL DEFAULT false,
    interval_minutes integer NOT NULL DEFAULT 120 CHECK(interval_minutes BETWEEN 15 AND 1440),
    actor jsonb NOT NULL, last_run_at timestamptz, last_run_uid text
);
