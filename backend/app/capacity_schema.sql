-- Additive schema 3 capacity storage. Apply after schema.sql, in its transaction.
ALTER TABLE app.business_record ADD COLUMN IF NOT EXISTS customer_uid text;
CREATE INDEX IF NOT EXISTS business_record_customer_idx
    ON app.business_record(store_key,customer_uid,record_key);
CREATE SEQUENCE IF NOT EXISTS app.domain_identifier_seq START 1000000000;
CREATE TABLE IF NOT EXISTS app.business_list_record (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_key text NOT NULL, attribute text NOT NULL, customer_uid text,
    payload jsonb NOT NULL, version bigint NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS business_list_customer_idx
    ON app.business_list_record(store_key,attribute,customer_uid,id);
CREATE TABLE IF NOT EXISTS app.customer_version (
    customer_uid text PRIMARY KEY, version bigint NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS app.projection_generation (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_epoch bigint NOT NULL, business_date date NOT NULL,
    metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.projection_current (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    generation bigint REFERENCES app.projection_generation(id),
    ordering_version bigint NOT NULL DEFAULT 0, dirty boolean NOT NULL DEFAULT true
);
INSERT INTO app.projection_current(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS app.projection_cursor (
    token_hash text PRIMARY KEY, subject text NOT NULL, payload jsonb NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes'
);
CREATE INDEX IF NOT EXISTS projection_cursor_expiry_idx ON app.projection_cursor(expires_at);
CREATE TABLE IF NOT EXISTS app.customer_projection (
    generation bigint NOT NULL REFERENCES app.projection_generation(id),
    customer_uid text NOT NULL, workbook jsonb NOT NULL, today jsonb,
    entity text, product text, payment_status text, dc_status text, officer text,
    tier text, tier_rank integer, ladder_indicative text,
    search_text text NOT NULL, display_name text NOT NULL,
    overdue numeric NOT NULL DEFAULT 0, outstanding numeric NOT NULL DEFAULT 0,
    dpd integer, next_action_on text, oldest_unpaid_on text,
    identity_only boolean NOT NULL DEFAULT false, has_sheet boolean NOT NULL DEFAULT false,
    unpaid boolean NOT NULL DEFAULT false, stale boolean NOT NULL DEFAULT false,
    worked boolean NOT NULL DEFAULT false, answers_waiting integer NOT NULL DEFAULT 0,
    contact_open boolean NOT NULL DEFAULT true, promise_history boolean NOT NULL DEFAULT false,
    kept_ptps integer NOT NULL DEFAULT 0,
    ptp_today integer NOT NULL DEFAULT 0, ptp_amount numeric NOT NULL DEFAULT 0,
    unreachable_today integer NOT NULL DEFAULT 0,
    PRIMARY KEY(generation,customer_uid)
);
CREATE INDEX IF NOT EXISTS customer_projection_desk_idx
    ON app.customer_projection(generation,entity,officer,tier_rank,dpd DESC,overdue DESC,customer_uid);
CREATE INDEX IF NOT EXISTS customer_projection_status_idx
    ON app.customer_projection(generation,payment_status,dc_status,product);
CREATE INDEX IF NOT EXISTS customer_projection_overdue_idx
    ON app.customer_projection(generation,overdue DESC,customer_uid);
CREATE INDEX IF NOT EXISTS customer_projection_outstanding_idx
    ON app.customer_projection(generation,outstanding DESC,customer_uid);
CREATE INDEX IF NOT EXISTS customer_projection_name_idx
    ON app.customer_projection(generation,display_name,customer_uid);
CREATE INDEX IF NOT EXISTS customer_projection_dpd_idx
    ON app.customer_projection(generation,dpd DESC,customer_uid);
CREATE INDEX IF NOT EXISTS customer_projection_next_idx
    ON app.customer_projection(generation,next_action_on,customer_uid);
-- Case history reads use customer first, while the existing primary key is month first.
CREATE INDEX IF NOT EXISTS customer_month_customer_idx
    ON records.customer_month(customer_uid,month DESC);

-- Immutable customer evidence avoids scanning a full reconciliation JSON book
-- for each case read. Source versions remain the monetary authority.
CREATE TABLE IF NOT EXISTS records.customer_payment_evidence (
    sequence bigint NOT NULL REFERENCES records.payment_reconciliation_version(sequence),
    customer_uid text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY(sequence, customer_uid)
);
DROP TRIGGER IF EXISTS customer_payment_evidence_no_change ON records.customer_payment_evidence;
CREATE TRIGGER customer_payment_evidence_no_change
    BEFORE UPDATE OR DELETE ON records.customer_payment_evidence
    FOR EACH ROW EXECUTE FUNCTION records.payment_reconciliation_no_change();
CREATE TABLE IF NOT EXISTS records.customer_payment_evidence_publication (
    sequence bigint PRIMARY KEY REFERENCES records.payment_reconciliation_version(sequence),
    completed_at timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS customer_payment_evidence_publication_no_change ON records.customer_payment_evidence_publication;
CREATE TRIGGER customer_payment_evidence_publication_no_change
    BEFORE UPDATE OR DELETE ON records.customer_payment_evidence_publication
    FOR EACH ROW EXECUTE FUNCTION records.payment_reconciliation_no_change();
