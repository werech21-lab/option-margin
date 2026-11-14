-- OptionMargin Postgres schema for FAR 52.222-43 margin recovery.
-- Fourteen tables. Tenant tables isolate rows with app.current_tenant_id.
-- Reference tables (sources, snapshots, change events, wage rates, job runs)
-- have no tenant_id column; RLS still requires a tenant context to read them.
-- The Supabase service role bypasses RLS. Application roles do not.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. sources
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(32) NOT NULL CHECK (source_type IN ('SAM_WD', 'USASPENDING', 'ECFR')),
    base_url TEXT NOT NULL,
    last_checked_at TIMESTAMPTZ,
    health_status VARCHAR(32) NOT NULL DEFAULT 'OK',
    freshness_sla_hours INTEGER NOT NULL DEFAULT 24
);

-- 2. source_snapshots
CREATE TABLE IF NOT EXISTS source_snapshots (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    wd_id VARCHAR(64) NOT NULL,
    revision INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_published_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    document_hash CHAR(64) NOT NULL,
    normalized_content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    parser_version VARCHAR(64) NOT NULL
);

-- 3. change_events
CREATE TABLE IF NOT EXISTS change_events (
    id TEXT PRIMARY KEY,
    wd_id VARCHAR(64) NOT NULL,
    previous_revision INTEGER,
    current_revision INTEGER,
    source_url TEXT NOT NULL,
    source_published_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    document_hash CHAR(64) NOT NULL,
    changed_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_locations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    parser_version VARCHAR(64) NOT NULL,
    gate_decision VARCHAR(16) NOT NULL CHECK (gate_decision IN ('ARCHIVE', 'IGNORE', 'ANALYZE'))
);

-- 4. wage_rates
CREATE TABLE IF NOT EXISTS wage_rates (
    id TEXT PRIMARY KEY,
    wd_id VARCHAR(64) NOT NULL,
    revision INTEGER NOT NULL,
    occupation_code VARCHAR(16) NOT NULL,
    occupation_title VARCHAR(255) NOT NULL,
    locality VARCHAR(255) NOT NULL,
    hourly_rate NUMERIC(10,4) NOT NULL,
    hw_rate NUMERIC(10,4) NOT NULL,
    source_published_at TIMESTAMPTZ,
    effective_at TIMESTAMPTZ,
    evidence_span TEXT NOT NULL DEFAULT '',
    UNIQUE (wd_id, revision, occupation_code, locality)
);

-- 5. contracts
CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id VARCHAR(64) NOT NULL UNIQUE,
    award_id VARCHAR(64),
    title VARCHAR(255),
    agency_name VARCHAR(255),
    naics_code VARCHAR(16) NOT NULL DEFAULT '561720',
    recipient_name VARCHAR(255),
    place_of_performance_county VARCHAR(128),
    place_of_performance_state VARCHAR(64),
    mapped_wd_id VARCHAR(64),
    far_clause_version VARCHAR(64) NOT NULL DEFAULT 'FAR 52.222-43',
    is_cba BOOLEAN NOT NULL DEFAULT FALSE,
    fica_rate NUMERIC(10,4) NOT NULL DEFAULT 0.0765,
    futa_rate NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    suta_rate NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    wc_rate NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    current_option_year INTEGER NOT NULL DEFAULT 1,
    next_option_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. contract_versions
CREATE TABLE IF NOT EXISTS contract_versions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id VARCHAR(64) NOT NULL REFERENCES contracts(contract_id),
    modification_number VARCHAR(32) NOT NULL,
    sf30_document_hash CHAR(64) NOT NULL,
    incorporated_wd_id VARCHAR(64),
    incorporated_wd_revision INTEGER,
    published_date DATE,
    verified_receipt_date DATE,
    effective_at DATE,
    is_bilateral_agreed BOOLEAN NOT NULL DEFAULT FALSE,
    agreed_adjustment_amount NUMERIC(12,2),
    evidence_span TEXT NOT NULL DEFAULT '',
    UNIQUE (contract_id, modification_number)
);

-- 7. contract_occupation_mappings
CREATE TABLE IF NOT EXISTS contract_occupation_mappings (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id VARCHAR(64) NOT NULL REFERENCES contracts(contract_id),
    client_job_code VARCHAR(64) NOT NULL,
    wd_occupation_code VARCHAR(16) NOT NULL,
    wd_occupation_title VARCHAR(255) NOT NULL,
    is_supported_scope BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (tenant_id, contract_id, client_job_code)
);

-- 8. payroll_rows
CREATE TABLE IF NOT EXISTS payroll_rows (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id VARCHAR(64) NOT NULL REFERENCES contracts(contract_id),
    worker_hash CHAR(64) NOT NULL,
    occupation_code VARCHAR(16) NOT NULL,
    pay_period_start DATE NOT NULL,
    pay_period_end DATE NOT NULL,
    eligible_hours NUMERIC(10,2) NOT NULL,
    actual_prev_wage NUMERIC(10,4) NOT NULL,
    actual_new_wage NUMERIC(10,4) NOT NULL,
    actual_prev_hw NUMERIC(10,4) NOT NULL,
    actual_new_hw NUMERIC(10,4) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. adjustment_cases
CREATE TABLE IF NOT EXISTS adjustment_cases (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    case_id VARCHAR(64) NOT NULL UNIQUE,
    contract_id VARCHAR(64) NOT NULL REFERENCES contracts(contract_id),
    change_event_id TEXT REFERENCES change_events(id),
    status VARCHAR(32) NOT NULL CHECK (status IN ('POTENTIAL', 'INSUFFICIENT_DATA', 'SUPPORTED', 'SUBMITTED', 'AGREED', 'BILLED', 'PAID')),
    event_type VARCHAR(32) NOT NULL CHECK (event_type IN ('WAGE_REVISION', 'OPTION_PERIOD_ALERT')),
    estimated_monthly_exposure_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    annualized_exposure_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    agreed_adjustment_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    billed_collected_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    unbilled_leakage_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    evidence_complete BOOLEAN NOT NULL DEFAULT FALSE,
    missing_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_action TEXT NOT NULL DEFAULT '',
    verified_receipt_date DATE,
    filing_deadline_date DATE,
    rule_pack_version VARCHAR(32) NOT NULL DEFAULT 'US-SCLS-1.0',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. calculation_versions
CREATE TABLE IF NOT EXISTS calculation_versions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    case_id VARCHAR(64) NOT NULL REFERENCES adjustment_cases(case_id),
    version_num INTEGER NOT NULL,
    total_workers INTEGER NOT NULL DEFAULT 0,
    total_monthly_hours NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    mandatory_wage_delta NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    voluntary_wage_stripped NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    mandatory_hw_delta NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    accompanying_tax_hourly NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
    monthly_base_entitlement_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    monthly_hw_entitlement_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    monthly_tax_entitlement_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    total_monthly_entitlement_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    breakdown_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, version_num)
);

-- 11. evidence_links
CREATE TABLE IF NOT EXISTS evidence_links (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    case_id VARCHAR(64) NOT NULL REFERENCES adjustment_cases(case_id),
    field_name VARCHAR(128) NOT NULL,
    field_value TEXT NOT NULL,
    source_type VARCHAR(32) NOT NULL CHECK (source_type IN ('SAM_WD', 'SF30_MOD', 'PAYROLL_FEED')),
    document_hash CHAR(64) NOT NULL,
    citation_span TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. delivery_outbox
CREATE TABLE IF NOT EXISTS delivery_outbox (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    case_id VARCHAR(64) NOT NULL REFERENCES adjustment_cases(case_id),
    idempotency_key CHAR(64) NOT NULL UNIQUE,
    channel VARCHAR(32) NOT NULL CHECK (channel IN ('EMAIL', 'WEBHOOK', 'INTERNAL_TASK')),
    recipient VARCHAR(255) NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SENT', 'FAILED', 'DEAD_LETTER')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. billing_matches
CREATE TABLE IF NOT EXISTS billing_matches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    case_id VARCHAR(64) NOT NULL REFERENCES adjustment_cases(case_id),
    contract_id VARCHAR(64) NOT NULL REFERENCES contracts(contract_id),
    invoice_number VARCHAR(64) NOT NULL,
    billing_period VARCHAR(32) NOT NULL,
    expected_adjusted_rate NUMERIC(10,4) NOT NULL,
    actual_billed_rate NUMERIC(10,4) NOT NULL,
    hours_billed NUMERIC(10,2) NOT NULL,
    variance_leakage_usd NUMERIC(12,2) NOT NULL,
    reconciliation_status VARCHAR(32) NOT NULL CHECK (reconciliation_status IN ('MATCHED', 'UNDERBILLED_LEAKAGE', 'PENDING')),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. job_runs
CREATE TABLE IF NOT EXISTS job_runs (
    id TEXT PRIMARY KEY,
    job_type VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('CLAIMED', 'COMPLETED', 'FAILED')),
    worker_id VARCHAR(64) NOT NULL,
    lease_until TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_contracts_tenant ON contracts (tenant_id);
CREATE INDEX IF NOT EXISTS idx_cases_tenant ON adjustment_cases (tenant_id);
CREATE INDEX IF NOT EXISTS idx_payroll_contract ON payroll_rows (tenant_id, contract_id);
CREATE INDEX IF NOT EXISTS idx_outbox_tenant ON delivery_outbox (tenant_id, status);

ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE wage_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_occupation_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustment_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE calculation_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;

-- Shared reference data is readable only after the app sets the tenant context.
CREATE POLICY tenant_context_sources ON sources
    FOR SELECT USING (current_setting('app.current_tenant_id', true) IS NOT NULL
                      AND current_setting('app.current_tenant_id', true) <> '');
CREATE POLICY tenant_context_snapshots ON source_snapshots
    FOR SELECT USING (current_setting('app.current_tenant_id', true) IS NOT NULL
                      AND current_setting('app.current_tenant_id', true) <> '');
CREATE POLICY tenant_context_change_events ON change_events
    FOR SELECT USING (current_setting('app.current_tenant_id', true) IS NOT NULL
                      AND current_setting('app.current_tenant_id', true) <> '');
CREATE POLICY tenant_context_wage_rates ON wage_rates
    FOR SELECT USING (current_setting('app.current_tenant_id', true) IS NOT NULL
                      AND current_setting('app.current_tenant_id', true) <> '');
CREATE POLICY tenant_context_job_runs ON job_runs
    FOR SELECT USING (current_setting('app.current_tenant_id', true) IS NOT NULL
                      AND current_setting('app.current_tenant_id', true) <> '');

CREATE POLICY tenant_isolation_contracts ON contracts
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_contract_versions ON contract_versions
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_mappings ON contract_occupation_mappings
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_payroll ON payroll_rows
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_cases ON adjustment_cases
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_calculations ON calculation_versions
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_evidence ON evidence_links
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_outbox ON delivery_outbox
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
CREATE POLICY tenant_isolation_billing ON billing_matches
    FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
