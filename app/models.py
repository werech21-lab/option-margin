"""Fourteen persistence tables for the FAR 52.222-43 margin engine.

Column names follow the master specification. observed_at (when a document was
captured) stays distinct from effective_at (when a rate or modification binds).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import q2, q4
from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RateAmount(TypeDecorator):
    """Numeric(10,4) that always round-trips as Decimal."""

    impl = Numeric(10, 4)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q4(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q4(value)


class MoneyAmount(TypeDecorator):
    """Numeric(12,2) currency that always round-trips as Decimal."""

    impl = Numeric(12, 2)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q2(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q2(value)


class HoursAmount(TypeDecorator):
    """Numeric(10,2) hours that always round-trip as Decimal."""

    impl = Numeric(10, 2)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q2(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return q2(value)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('SAM_WD', 'USASPENDING', 'ECFR')", name="ck_sources_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="OK")
    freshness_sla_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    wd_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "gate_decision IN ('ARCHIVE', 'IGNORE', 'ANALYZE')",
            name="ck_change_events_gate",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    wd_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_locations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_decision: Mapped[str] = mapped_column(String(16), nullable=False)


class WageRate(Base):
    __tablename__ = "wage_rates"
    __table_args__ = (
        UniqueConstraint("wd_id", "revision", "occupation_code", "locality", name="uq_wage_rate_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    wd_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    occupation_code: Mapped[str] = mapped_column(String(16), nullable=False)
    occupation_title: Mapped[str] = mapped_column(String(255), nullable=False)
    locality: Mapped[str] = mapped_column(String(255), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    hw_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_span: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    award_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    naics_code: Mapped[str] = mapped_column(String(16), nullable=False, default="561720")
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place_of_performance_county: Mapped[str | None] = mapped_column(String(128), nullable=True)
    place_of_performance_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapped_wd_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    far_clause_version: Mapped[str] = mapped_column(String(64), nullable=False, default="FAR 52.222-43")
    is_cba: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fica_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0765"))
    futa_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    suta_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    wc_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    current_option_year: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_option_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    versions: Mapped[list[ContractVersion]] = relationship(back_populates="contract")
    cases: Mapped[list[AdjustmentCase]] = relationship(back_populates="contract")


class ContractVersion(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (
        UniqueConstraint("contract_id", "modification_number", name="uq_contract_mod"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), nullable=False)
    modification_number: Mapped[str] = mapped_column(String(32), nullable=False)
    sf30_document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    incorporated_wd_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    incorporated_wd_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_bilateral_agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agreed_adjustment_amount: Mapped[Decimal | None] = mapped_column(MoneyAmount(), nullable=True)
    evidence_span: Mapped[str] = mapped_column(Text, nullable=False, default="")

    contract: Mapped[Contract] = relationship(back_populates="versions")


class ContractOccupationMapping(Base):
    __tablename__ = "contract_occupation_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_id", "client_job_code", name="uq_occ_map"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), nullable=False)
    client_job_code: Mapped[str] = mapped_column(String(64), nullable=False)
    wd_occupation_code: Mapped[str] = mapped_column(String(16), nullable=False)
    wd_occupation_title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_supported_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PayrollRow(Base):
    __tablename__ = "payroll_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), nullable=False, index=True)
    worker_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occupation_code: Mapped[str] = mapped_column(String(16), nullable=False)
    pay_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    pay_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    eligible_hours: Mapped[Decimal] = mapped_column(HoursAmount(), nullable=False)
    actual_prev_wage: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    actual_new_wage: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    actual_prev_hw: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    actual_new_hw: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AdjustmentCase(Base):
    __tablename__ = "adjustment_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('POTENTIAL', 'INSUFFICIENT_DATA', 'SUPPORTED', 'SUBMITTED', 'AGREED', 'BILLED', 'PAID')",
            name="ck_cases_status",
        ),
        CheckConstraint(
            "event_type IN ('WAGE_REVISION', 'OPTION_PERIOD_ALERT')",
            name="ck_cases_event_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), nullable=False, index=True)
    change_event_id: Mapped[str | None] = mapped_column(ForeignKey("change_events.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_monthly_exposure_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    annualized_exposure_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    agreed_adjustment_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    billed_collected_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    unbilled_leakage_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    evidence_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verified_receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filing_deadline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rule_pack_version: Mapped[str] = mapped_column(String(32), nullable=False, default="US-SCLS-1.0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    contract: Mapped[Contract] = relationship(back_populates="cases")
    change_event: Mapped[ChangeEvent | None] = relationship()
    calculations: Mapped[list[CalculationVersion]] = relationship(
        back_populates="case",
        order_by="CalculationVersion.version_num",
    )
    evidence_links: Mapped[list[EvidenceLink]] = relationship(back_populates="case")
    outbox_rows: Mapped[list[DeliveryOutbox]] = relationship(back_populates="case")
    billing_matches: Mapped[list[BillingMatch]] = relationship(back_populates="case")


class CalculationVersion(Base):
    __tablename__ = "calculation_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version_num", name="uq_calc_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("adjustment_cases.case_id"), nullable=False, index=True)
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    total_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_monthly_hours: Mapped[Decimal] = mapped_column(HoursAmount(), nullable=False, default=Decimal("0.00"))
    mandatory_wage_delta: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    voluntary_wage_stripped: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    mandatory_hw_delta: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    accompanying_tax_hourly: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False, default=Decimal("0.0000"))
    monthly_base_entitlement_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    monthly_hw_entitlement_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    monthly_tax_entitlement_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    total_monthly_entitlement_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False, default=Decimal("0.00"))
    breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    case: Mapped[AdjustmentCase] = relationship(back_populates="calculations")


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('SAM_WD', 'SF30_MOD', 'PAYROLL_FEED')",
            name="ck_evidence_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("adjustment_cases.case_id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    citation_span: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    case: Mapped[AdjustmentCase] = relationship(back_populates="evidence_links")


class DeliveryOutbox(Base):
    __tablename__ = "delivery_outbox"
    __table_args__ = (
        CheckConstraint("channel IN ('EMAIL', 'WEBHOOK', 'INTERNAL_TASK')", name="ck_outbox_channel"),
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'DEAD_LETTER')",
            name="ck_outbox_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("adjustment_cases.case_id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    case: Mapped[AdjustmentCase] = relationship(back_populates="outbox_rows")


class BillingMatch(Base):
    __tablename__ = "billing_matches"
    __table_args__ = (
        CheckConstraint(
            "reconciliation_status IN ('MATCHED', 'UNDERBILLED_LEAKAGE', 'PENDING')",
            name="ck_billing_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("adjustment_cases.case_id"), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.contract_id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_adjusted_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    actual_billed_rate: Mapped[Decimal] = mapped_column(RateAmount(), nullable=False)
    hours_billed: Mapped[Decimal] = mapped_column(HoursAmount(), nullable=False)
    variance_leakage_usd: Mapped[Decimal] = mapped_column(MoneyAmount(), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    case: Mapped[AdjustmentCase] = relationship(back_populates="billing_matches")


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("status IN ('CLAIMED', 'COMPLETED', 'FAILED')", name="ck_job_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
