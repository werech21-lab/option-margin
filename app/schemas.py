"""Pydantic v2 contracts for calculation results, gates, and the public case JSON."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Float inputs are prohibited in financial schemas. Pass Decimal or str.")
    return Decimal(str(value))


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HourlyComponents(APIModel):
    eligible_wage_delta: Decimal
    voluntary_wage_stripped: Decimal
    eligible_hw_delta: Decimal
    voluntary_hw_stripped: Decimal
    tax_rate_total: Decimal
    tax_per_hour: Decimal
    overhead: Decimal
    ga: Decimal
    profit: Decimal
    per_hour_entitlement: Decimal

    @field_validator(
        "eligible_wage_delta",
        "voluntary_wage_stripped",
        "eligible_hw_delta",
        "voluntary_hw_stripped",
        "tax_rate_total",
        "tax_per_hour",
        "overhead",
        "ga",
        "profit",
        "per_hour_entitlement",
        mode="before",
    )
    @classmethod
    def decimals_only(cls, value: Any) -> Decimal:
        return _reject_float(value)


class PriceAdjustment(HourlyComponents):
    total_workers: int
    total_hours: Decimal
    monthly_base_entitlement_usd: Decimal
    monthly_hw_entitlement_usd: Decimal
    monthly_tax_entitlement_usd: Decimal
    total_monthly_entitlement_usd: Decimal
    annualized_exposure_usd: Decimal

    @field_validator(
        "total_hours",
        "monthly_base_entitlement_usd",
        "monthly_hw_entitlement_usd",
        "monthly_tax_entitlement_usd",
        "total_monthly_entitlement_usd",
        "annualized_exposure_usd",
        mode="before",
    )
    @classmethod
    def money_decimals(cls, value: Any) -> Decimal:
        return _reject_float(value)


class GateAssessment(APIModel):
    status: str
    gate_decision: str
    event_type: str
    evidence_complete: bool
    missing_fields: list[str]
    next_action: str
    verified_receipt_date: date | None = None
    filing_deadline_date: date | None = None
    rule_pack_version: str
    opens_case: bool
    unsupported_scope: bool = False


class CaseContract(APIModel):
    case_id: str
    contract_id: str
    status: str
    event_type: str
    estimated_monthly_exposure_usd: str
    evidence_complete: bool
    missing_fields: list[str]
    next_action: str
    rule_pack_version: str


class ScrubbedPayrollRow(APIModel):
    worker_hash: str
    occupation_code: str
    client_job_code: str
    eligible_hours: Decimal
    actual_prev_wage: Decimal
    actual_new_wage: Decimal
    actual_prev_hw: Decimal
    actual_new_hw: Decimal
    pay_period_start: date | None = None
    pay_period_end: date | None = None

    @field_validator(
        "eligible_hours",
        "actual_prev_wage",
        "actual_new_wage",
        "actual_prev_hw",
        "actual_new_hw",
        mode="before",
    )
    @classmethod
    def decimals_only(cls, value: Any) -> Decimal:
        return _reject_float(value)


class ParsedSF30(APIModel):
    modification_number: str | None = None
    incorporated_wd_id: str | None = None
    incorporated_wd_revision: int | None = None
    verified_receipt_date: date | None = None
    far_52_222_43_applicable: bool = False
    document_hash: str
    sanitized: bool = False
    evidence_span: str = ""
    injection_lines_removed: int = 0


class ProspectCard(APIModel):
    recipient_name: str
    award_id: str
    agency_name: str
    naics_code: str
    county: str
    state: str
    wd_id: str | None = None
    wd_revision: int | None = None
    hourly_delta: Decimal
    sensitivity_per_10000_hours_usd: Decimal
    illustrative_080_sensitivity_usd: Decimal
    legal_entitlement_claimed: bool = False
    source: str

    @field_validator("hourly_delta", "sensitivity_per_10000_hours_usd", "illustrative_080_sensitivity_usd", mode="before")
    @classmethod
    def decimals_only(cls, value: Any) -> Decimal:
        return _reject_float(value)


class LeadRequest(APIModel):
    company_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=200)
    contract_id: str = Field(default="", max_length=64)


class HealthResponse(APIModel):
    status: str
    rule_pack_version: str
    checked_at: datetime
