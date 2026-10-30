"""All 14 Core Database Tables with Audit Fields and Strict Decimal Types.

Supports SQLAlchemy 2.0 ORM in production and seamless air-gapped SQLite execution.
"""

import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Any
from app.database import Base, HAS_SQLALCHEMY


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


if HAS_SQLALCHEMY:
    from sqlalchemy import (  # type: ignore
        String,
        Integer,
        Boolean,
        Date,
        DateTime,
        Numeric,
        ForeignKey,
        Text,
        UniqueConstraint,
    )
    from sqlalchemy.orm import Mapped, mapped_column  # type: ignore

    def col(*args: Any, **kwargs: Any) -> Any:
        return mapped_column(*args, **kwargs)
else:
    from app.database import _ColumnField

    class _DummyType:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    String = Integer = Boolean = Date = DateTime = Numeric = ForeignKey = Text = UniqueConstraint = _DummyType  # type: ignore

    def col(*args: Any, **kwargs: Any) -> Any:
        default = kwargs.get("default")
        unique = kwargs.get("unique", False)
        if callable(default):
            return _ColumnField(default_factory=default, unique=unique)
        return _ColumnField(default=default, unique=unique)


class Organization(Base):
    __tablename__ = "organizations"
    _unique_constraints = [["uei"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    name = col(String(255), nullable=False)
    uei = col(String(32), unique=True, nullable=False)
    cage_code = col(String(16), nullable=True)
    primary_naics = col(String(16), default="561720", nullable=False)
    fica_rate = col(Numeric(6, 4), default=Decimal("0.0765"), nullable=False)
    futa_rate = col(Numeric(6, 4), default=Decimal("0.0060"), nullable=False)
    suta_rate = col(Numeric(6, 4), default=Decimal("0.0210"), nullable=False)
    workers_comp_rate = col(Numeric(6, 4), default=Decimal("0.0315"), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)
    updated_at = col(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    _unique_constraints = [["email"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    email = col(String(255), unique=True, nullable=False)
    full_name = col(String(255), nullable=False)
    role = col(String(50), default="CFO", nullable=False)
    is_active = col(Boolean, default=True, nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class WageDetermination(Base):
    __tablename__ = "wage_determinations"
    _unique_constraints = [["wd_number", "revision_number"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    wd_number = col(String(64), nullable=False)
    revision_number = col(Integer, nullable=False)
    locality_state = col(String(64), nullable=False)
    locality_county = col(String(128), nullable=False)
    source_published_at = col(Date, nullable=False)
    raw_content_hash = col(String(64), nullable=False)
    semantic_rate_hash = col(String(64), nullable=False)
    hw_rate_standard = col(Numeric(10, 4), nullable=False)
    hw_rate_eo13706 = col(Numeric(10, 4), nullable=False)
    source_url = col(Text, nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class WDOccupationRate(Base):
    __tablename__ = "wd_occupation_rates"
    _unique_constraints = [["wd_id", "occupation_code"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    wd_id = col(String(36), ForeignKey("wage_determinations.id"), nullable=False)
    occupation_code = col(String(16), nullable=False)
    occupation_title = col(String(255), nullable=False)
    hourly_rate = col(Numeric(10, 4), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class Contract(Base):
    __tablename__ = "contracts"
    _unique_constraints = [["org_id", "piid"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    piid = col(String(64), nullable=False)
    agency_name = col(String(255), nullable=False)
    naics_code = col(String(16), default="561720", nullable=False)
    psc_code = col(String(16), default="S201", nullable=False)
    pop_state = col(String(64), nullable=False)
    pop_county = col(String(128), nullable=False)
    wd_number = col(String(64), nullable=False)
    active_wd_id = col(String(36), ForeignKey("wage_determinations.id"), nullable=True)
    current_option_year = col(Integer, default=0, nullable=False)
    next_option_start_date = col(Date, nullable=False)
    annual_estimated_hours = col(Numeric(12, 2), default=Decimal("20800.00"), nullable=False)
    is_eo13706_applicable = col(Boolean, default=True, nullable=False)
    has_complex_cba = col(Boolean, default=False, nullable=False)
    status = col(String(32), default="ACTIVE", nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class ContractModification(Base):
    __tablename__ = "contract_modifications"
    _unique_constraints = [["contract_id", "mod_number"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    contract_id = col(String(36), ForeignKey("contracts.id"), nullable=False)
    mod_number = col(String(32), nullable=False)
    mod_type = col(String(64), nullable=False)
    incorporated_wd_id = col(String(36), ForeignKey("wage_determinations.id"), nullable=True)
    effective_date = col(Date, nullable=False)
    verified_receipt_date = col(Date, nullable=False)
    notification_deadline_date = col(Date, nullable=False)
    written_extension_date = col(Date, nullable=True)
    sf30_block14_text = col(Text, nullable=False)
    document_hash = col(String(64), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class OccupationMapping(Base):
    __tablename__ = "occupation_mappings"
    _unique_constraints = [["org_id", "internal_job_code"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    internal_job_code = col(String(64), nullable=False)
    internal_job_title = col(String(255), nullable=False)
    scls_occupation_code = col(String(16), nullable=False)
    scls_occupation_title = col(String(255), nullable=False)
    is_verified = col(Boolean, default=True, nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class PayrollBatch(Base):
    __tablename__ = "payroll_batches"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    contract_id = col(String(36), ForeignKey("contracts.id"), nullable=False)
    period_start = col(Date, nullable=False)
    period_end = col(Date, nullable=False)
    source_system = col(String(64), default="ADP_WORKFORCE_NOW", nullable=False)
    total_regular_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    total_overtime_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    total_vacation_holiday_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    pii_fields_stripped = col(Integer, default=0, nullable=False)
    batch_hash = col(String(64), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class PayrollLineItem(Base):
    __tablename__ = "payroll_line_items"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    batch_id = col(String(36), ForeignKey("payroll_batches.id"), nullable=False)
    worker_hash = col(String(64), nullable=False)
    internal_job_code = col(String(64), nullable=False)
    scls_occupation_code = col(String(16), nullable=True)
    regular_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    overtime_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    vacation_holiday_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    actual_prev_wage_rate = col(Numeric(10, 4), nullable=False)
    actual_new_wage_rate = col(Numeric(10, 4), nullable=False)
    actual_prev_hw_rate = col(Numeric(10, 4), nullable=False)
    actual_new_hw_rate = col(Numeric(10, 4), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class AdjustmentCase(Base):
    __tablename__ = "adjustment_cases"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    contract_id = col(String(36), ForeignKey("contracts.id"), nullable=False)
    modification_id = col(String(36), ForeignKey("contract_modifications.id"), nullable=True)
    old_wd_id = col(String(36), ForeignKey("wage_determinations.id"), nullable=False)
    new_wd_id = col(String(36), ForeignKey("wage_determinations.id"), nullable=False)
    state_gate = col(String(32), nullable=False)
    lifecycle_status = col(String(32), default="DETECTED", nullable=False)
    is_pre_option_alert = col(Boolean, default=False, nullable=False)
    days_until_option = col(Integer, nullable=True)
    days_remaining_30d_clock = col(Integer, nullable=True)
    is_late_notice_flagged = col(Boolean, default=False, nullable=False)
    total_eligible_hours = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    total_eligible_wage_delta = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    total_eligible_hw_delta = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    total_accompanying_taxes_wc = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    voluntary_raise_excluded_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    overhead_excluded_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    ga_excluded_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    profit_excluded_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    total_claim_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    gate_reason = col(Text, nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)
    updated_at = col(DateTime, default=utcnow, nullable=False)


class CalculationLedgerEntry(Base):
    __tablename__ = "calculation_ledger_entries"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    case_id = col(String(36), ForeignKey("adjustment_cases.id"), nullable=False)
    scls_occupation_code = col(String(16), nullable=False)
    worker_hash = col(String(64), nullable=False)
    eligible_wage_hours = col(Numeric(12, 4), nullable=False)
    eligible_hw_hours = col(Numeric(12, 4), nullable=False)
    overtime_hours_excluded_from_hw = col(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    w_prev = col(Numeric(10, 4), nullable=False)
    w_req_new = col(Numeric(10, 4), nullable=False)
    w_act_new = col(Numeric(10, 4), nullable=False)
    eligible_hourly_wage_delta = col(Numeric(10, 4), nullable=False)
    voluntary_hourly_exclusion = col(Numeric(10, 4), nullable=False)
    hw_prev = col(Numeric(10, 4), nullable=False)
    hw_req_new = col(Numeric(10, 4), nullable=False)
    hw_act_new = col(Numeric(10, 4), nullable=False)
    eligible_hourly_hw_delta = col(Numeric(10, 4), nullable=False)
    combined_tax_wc_rate = col(Numeric(6, 4), nullable=False)
    tax_wc_hourly_delta = col(Numeric(10, 4), nullable=False)
    line_wage_entitlement = col(Numeric(14, 2), nullable=False)
    line_hw_entitlement = col(Numeric(14, 2), nullable=False)
    line_tax_wc_entitlement = col(Numeric(14, 2), nullable=False)
    line_total_claim = col(Numeric(14, 2), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    case_id = col(String(36), ForeignKey("adjustment_cases.id"), nullable=False)
    source_doc_type = col(String(64), nullable=False)
    source_doc_identifier = col(String(128), nullable=False)
    extracted_field_name = col(String(128), nullable=False)
    extracted_value = col(String(128), nullable=False)
    page_number = col(Integer, default=1, nullable=False)
    char_start = col(Integer, default=0, nullable=False)
    char_end = col(Integer, default=0, nullable=False)
    verbatim_quote = col(Text, nullable=False)
    confidence_score = col(Numeric(5, 4), default=Decimal("1.0000"), nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class BillingReconciliation(Base):
    __tablename__ = "billing_reconciliations"

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=False)
    case_id = col(String(36), ForeignKey("adjustment_cases.id"), nullable=False)
    executed_mod_number = col(String(32), nullable=True)
    agreed_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    invoice_number = col(String(64), nullable=True)
    billed_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    billed_at = col(Date, nullable=True)
    paid_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    paid_at = col(Date, nullable=True)
    variance_amount = col(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    reconciliation_status = col(String(32), default="PENDING_MOD", nullable=False)
    created_at = col(DateTime, default=utcnow, nullable=False)


class TransactionalOutbox(Base):
    __tablename__ = "transactional_outbox"
    _unique_constraints = [["idempotency_key"]]

    id = col(String(36), primary_key=True, default=gen_uuid)
    org_id = col(String(36), ForeignKey("organizations.id"), nullable=True)
    idempotency_key = col(String(128), unique=True, nullable=False)
    task_type = col(String(64), nullable=False)
    payload_json = col(Text, nullable=False)
    status = col(String(32), default="PENDING", nullable=False)
    retry_count = col(Integer, default=0, nullable=False)
    result_summary = col(Text, nullable=True)
    created_at = col(DateTime, default=utcnow, nullable=False)
    processed_at = col(DateTime, nullable=True)
