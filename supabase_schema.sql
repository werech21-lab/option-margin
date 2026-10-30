-- ============================================================================
-- OptionMargin — Supabase PostgreSQL DDL + Row-Level Security (RLS)
-- Complete 14-Table Production Schema for FAR 52.222-43 Margin Recovery
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. organizations
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    uei VARCHAR(32) UNIQUE NOT NULL,
    cage_code VARCHAR(16),
    primary_naics VARCHAR(16) NOT NULL DEFAULT '561720',
    fica_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0765,
    futa_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0060,
    suta_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0210,
    workers_comp_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0315,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('CFO', 'CONTRACTS_MANAGER', 'ADMIN', 'AUDITOR')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. wage_determinations
CREATE TABLE IF NOT EXISTS wage_determinations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    wd_number VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    locality_state VARCHAR(64) NOT NULL,
    locality_county VARCHAR(128) NOT NULL,
    source_published_at DATE NOT NULL,
    raw_content_hash CHAR(64) NOT NULL,
    semantic_rate_hash CHAR(64) NOT NULL,
    hw_rate_standard NUMERIC(10,4) NOT NULL,
    hw_rate_eo13706 NUMERIC(10,4) NOT NULL,
    source_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (wd_number, revision_number)
);

-- 4. wd_occupation_rates
CREATE TABLE IF NOT EXISTS wd_occupation_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    wd_id UUID NOT NULL REFERENCES wage_determinations(id) ON DELETE CASCADE,
    occupation_code VARCHAR(16) NOT NULL,
    occupation_title VARCHAR(255) NOT NULL,
    hourly_rate NUMERIC(10,4) NOT NULL CHECK (hourly_rate >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (wd_id, occupation_code)
);

-- 5. contracts
CREATE TABLE IF NOT EXISTS contracts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    piid VARCHAR(64) NOT NULL,
    agency_name VARCHAR(255) NOT NULL,
    naics_code VARCHAR(16) NOT NULL DEFAULT '561720',
    psc_code VARCHAR(16) NOT NULL DEFAULT 'S201',
    pop_state VARCHAR(64) NOT NULL,
    pop_county VARCHAR(128) NOT NULL,
    wd_number VARCHAR(64) NOT NULL,
    active_wd_id UUID REFERENCES wage_determinations(id),
    current_option_year INTEGER NOT NULL DEFAULT 0,
    next_option_start_date DATE NOT NULL,
    annual_estimated_hours NUMERIC(12,2) NOT NULL DEFAULT 20800.00,
    is_eo13706_applicable BOOLEAN NOT NULL DEFAULT TRUE,
    has_complex_cba BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, piid)
);

-- 6. contract_modifications (SF-30)
CREATE TABLE IF NOT EXISTS contract_modifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    mod_number VARCHAR(32) NOT NULL,
    mod_type VARCHAR(64) NOT NULL CHECK (mod_type IN ('OPTION_EXERCISE', 'WD_INCORPORATION', 'ADMIN_CHANGE', 'BILATERAL_SETTLEMENT')),
    incorporated_wd_id UUID REFERENCES wage_determinations(id),
    effective_date DATE NOT NULL,
    verified_receipt_date DATE NOT NULL,
    notification_deadline_date DATE NOT NULL,
    written_extension_date DATE,
    sf30_block14_text TEXT NOT NULL,
    document_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contract_id, mod_number)
);

-- 7. occupation_mappings
CREATE TABLE IF NOT EXISTS occupation_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    internal_job_code VARCHAR(64) NOT NULL,
    internal_job_title VARCHAR(255) NOT NULL,
    scls_occupation_code VARCHAR(16) NOT NULL,
    scls_occupation_title VARCHAR(255) NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, internal_job_code)
);

-- 8. payroll_batches
CREATE TABLE IF NOT EXISTS payroll_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    source_system VARCHAR(64) NOT NULL DEFAULT 'ADP_WORKFORCE_NOW',
    total_regular_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    total_overtime_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    total_vacation_holiday_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    pii_fields_stripped INTEGER NOT NULL DEFAULT 0,
    batch_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. payroll_line_items (Zero-PII)
CREATE TABLE IF NOT EXISTS payroll_line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    batch_id UUID NOT NULL REFERENCES payroll_batches(id) ON DELETE CASCADE,
    worker_hash VARCHAR(64) NOT NULL,
    internal_job_code VARCHAR(64) NOT NULL,
    scls_occupation_code VARCHAR(16),
    regular_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    overtime_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    vacation_holiday_hours NUMERIC(12,4) NOT NULL DEFAULT 0,
    actual_prev_wage_rate NUMERIC(10,4) NOT NULL,
    actual_new_wage_rate NUMERIC(10,4) NOT NULL,
    actual_prev_hw_rate NUMERIC(10,4) NOT NULL,
    actual_new_hw_rate NUMERIC(10,4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. adjustment_cases
CREATE TABLE IF NOT EXISTS adjustment_cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    modification_id UUID REFERENCES contract_modifications(id),
    old_wd_id UUID NOT NULL REFERENCES wage_determinations(id),
    new_wd_id UUID NOT NULL REFERENCES wage_determinations(id),
    state_gate VARCHAR(32) NOT NULL CHECK (state_gate IN ('ARCHIVE', 'IGNORE', 'POTENTIAL', 'INSUFFICIENT_DATA', 'SUPPORTED')),
    lifecycle_status VARCHAR(32) NOT NULL CHECK (lifecycle_status IN ('DETECTED', 'SUPPORTED', 'SUBMITTED', 'AGREED', 'BILLED', 'PAID')),
    is_pre_option_alert BOOLEAN NOT NULL DEFAULT FALSE,
    days_until_option INTEGER,
    days_remaining_30d_clock INTEGER,
    is_late_notice_flagged BOOLEAN NOT NULL DEFAULT FALSE,
    total_eligible_hours NUMERIC(12,4) NOT NULL DEFAULT 0.0000,
    total_eligible_wage_delta NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    total_eligible_hw_delta NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    total_accompanying_taxes_wc NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    voluntary_raise_excluded_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    overhead_excluded_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00 CHECK (overhead_excluded_amount = 0.00),
    ga_excluded_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00 CHECK (ga_excluded_amount = 0.00),
    profit_excluded_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00 CHECK (profit_excluded_amount = 0.00),
    total_claim_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    gate_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. calculation_ledger_entries
CREATE TABLE IF NOT EXISTS calculation_ledger_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES adjustment_cases(id) ON DELETE CASCADE,
    scls_occupation_code VARCHAR(16) NOT NULL,
    worker_hash VARCHAR(64) NOT NULL,
    eligible_wage_hours NUMERIC(12,4) NOT NULL,
    eligible_hw_hours NUMERIC(12,4) NOT NULL,
    overtime_hours_excluded_from_hw NUMERIC(12,4) NOT NULL DEFAULT 0.0000,
    w_prev NUMERIC(10,4) NOT NULL,
    w_req_new NUMERIC(10,4) NOT NULL,
    w_act_new NUMERIC(10,4) NOT NULL,
    eligible_hourly_wage_delta NUMERIC(10,4) NOT NULL,
    voluntary_hourly_exclusion NUMERIC(10,4) NOT NULL,
    hw_prev NUMERIC(10,4) NOT NULL,
    hw_req_new NUMERIC(10,4) NOT NULL,
    hw_act_new NUMERIC(10,4) NOT NULL,
    eligible_hourly_hw_delta NUMERIC(10,4) NOT NULL,
    combined_tax_wc_rate NUMERIC(6,4) NOT NULL,
    tax_wc_hourly_delta NUMERIC(10,4) NOT NULL,
    line_wage_entitlement NUMERIC(14,2) NOT NULL,
    line_hw_entitlement NUMERIC(14,2) NOT NULL,
    line_tax_wc_entitlement NUMERIC(14,2) NOT NULL,
    line_total_claim NUMERIC(14,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. evidence_spans
CREATE TABLE IF NOT EXISTS evidence_spans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES adjustment_cases(id) ON DELETE CASCADE,
    source_doc_type VARCHAR(64) NOT NULL CHECK (source_doc_type IN ('WD_PUBLIC', 'SF30_MOD', 'PAYROLL_REGISTER', 'TAX_RATE_NOTICE')),
    source_doc_identifier VARCHAR(128) NOT NULL,
    extracted_field_name VARCHAR(128) NOT NULL,
    extracted_value VARCHAR(128) NOT NULL,
    page_number INTEGER NOT NULL DEFAULT 1,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    verbatim_quote TEXT NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL DEFAULT 1.0000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. billing_reconciliations
CREATE TABLE IF NOT EXISTS billing_reconciliations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES adjustment_cases(id) ON DELETE CASCADE,
    executed_mod_number VARCHAR(32),
    agreed_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    invoice_number VARCHAR(64),
    billed_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    billed_at DATE,
    paid_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    paid_at DATE,
    variance_amount NUMERIC(14,2) NOT NULL DEFAULT 0.00,
    reconciliation_status VARCHAR(32) NOT NULL DEFAULT 'PENDING_MOD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. transactional_outbox
CREATE TABLE IF NOT EXISTS transactional_outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    task_type VARCHAR(64) NOT NULL CHECK (task_type IN ('prospect_audit', 'evidence_package_build', 'co_notification_dispatch', 'billing_sync')),
    payload_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    result_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- ============================================================================
-- Row-Level Security (RLS) Tenant Isolation Policies
-- ============================================================================
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_modifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE occupation_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustment_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE calculation_ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_reconciliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactional_outbox ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_contracts ON contracts
    USING (org_id = (current_setting('app.current_org_id', true))::uuid);
CREATE POLICY tenant_isolation_cases ON adjustment_cases
    USING (org_id = (current_setting('app.current_org_id', true))::uuid);
CREATE POLICY tenant_isolation_payroll ON payroll_line_items
    USING (org_id = (current_setting('app.current_org_id', true))::uuid);
