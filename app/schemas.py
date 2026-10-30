"""Strict Pydantic Schemas & JSON Contracts enforcing zero-float Decimal math.

Supports both Pydantic v2 (`field_validator`, `ConfigDict`, `model_dump_json`) and Pydantic v1 (`validator`, `Config`).
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict, field_validator  # type: ignore
    HAS_PYDANTIC_V2 = True
except ImportError:
    from pydantic import validator  # type: ignore
    HAS_PYDANTIC_V2 = False


def _reject_float(v: Any) -> Decimal:
    if isinstance(v, float):
        raise ValueError("Float inputs are strictly prohibited in financial schemas. Pass Decimal or str.")
    return Decimal(str(v))


class _CompatBaseModel(BaseModel):
    if HAS_PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        if HAS_PYDANTIC_V2 and hasattr(super(), "model_dump_json"):
            return super().model_dump_json(*args, **kwargs)  # type: ignore
        return self.json(*args, **kwargs)


def compat_validator(*fields: str):
    if HAS_PYDANTIC_V2:
        return field_validator(*fields, mode="before")
    return validator(*fields, pre=True)


class StateGate(str, Enum):
    ARCHIVE = "ARCHIVE"
    IGNORE = "IGNORE"
    POTENTIAL = "POTENTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SUPPORTED = "SUPPORTED"


class LifecycleStatus(str, Enum):
    DETECTED = "DETECTED"
    SUPPORTED = "SUPPORTED"
    SUBMITTED = "SUBMITTED"
    AGREED = "AGREED"
    BILLED = "BILLED"
    PAID = "PAID"


class StatutoryTaxConfig(_CompatBaseModel):
    fica_rate: Decimal = Field(default=Decimal("0.0765"))
    futa_rate: Decimal = Field(default=Decimal("0.0060"))
    suta_rate: Decimal = Field(default=Decimal("0.0210"))
    workers_comp_rate: Decimal = Field(default=Decimal("0.0315"))
    overhead_rate: Decimal = Field(default=Decimal("0.0000"))
    ga_rate: Decimal = Field(default=Decimal("0.0000"))
    profit_rate: Decimal = Field(default=Decimal("0.0000"))

    @compat_validator(
        "fica_rate",
        "futa_rate",
        "suta_rate",
        "workers_comp_rate",
        "overhead_rate",
        "ga_rate",
        "profit_rate",
    )
    @classmethod
    def validate_no_float(cls, v: Any) -> Decimal:
        return _reject_float(v)

    @property
    def combined_statutory_rate(self) -> Decimal:
        return self.fica_rate + self.futa_rate + self.suta_rate + self.workers_comp_rate


class EvidenceSpanSchema(_CompatBaseModel):
    source_doc_type: str
    source_doc_identifier: str
    extracted_field_name: str
    extracted_value: str
    page_number: int = 1
    char_start: int = 0
    char_end: int = 0
    verbatim_quote: str
    confidence_score: Decimal = Decimal("1.0000")


class ScrubbedPayrollLine(_CompatBaseModel):
    worker_hash: str
    internal_job_code: str
    scls_occupation_code: str | None = None
    regular_hours: Decimal
    overtime_hours: Decimal = Decimal("0.0000")
    vacation_holiday_hours: Decimal = Decimal("0.0000")
    actual_prev_wage_rate: Decimal
    actual_new_wage_rate: Decimal
    actual_prev_hw_rate: Decimal
    actual_new_hw_rate: Decimal

    @compat_validator(
        "regular_hours",
        "overtime_hours",
        "vacation_holiday_hours",
        "actual_prev_wage_rate",
        "actual_new_wage_rate",
        "actual_prev_hw_rate",
        "actual_new_hw_rate",
    )
    @classmethod
    def validate_decimals(cls, v: Any) -> Decimal:
        return _reject_float(v)


class LedgerLineResult(_CompatBaseModel):
    worker_hash: str
    scls_occupation_code: str
    eligible_wage_hours: Decimal
    eligible_hw_hours: Decimal
    overtime_hours_excluded_from_hw: Decimal
    w_prev: Decimal
    w_req_new: Decimal
    w_act_new: Decimal
    eligible_hourly_wage_delta: Decimal
    voluntary_hourly_exclusion: Decimal
    hw_prev: Decimal
    hw_req_new: Decimal
    hw_act_new: Decimal
    eligible_hourly_hw_delta: Decimal
    combined_tax_wc_rate: Decimal
    tax_wc_hourly_delta: Decimal
    line_wage_entitlement: Decimal
    line_hw_entitlement: Decimal
    line_tax_wc_entitlement: Decimal
    line_total_claim: Decimal


class QuantEvaluationResult(_CompatBaseModel):
    state_gate: StateGate
    lifecycle_status: LifecycleStatus
    is_pre_option_alert: bool
    days_until_option: int | None
    days_remaining_30d_clock: int | None
    is_late_notice_flagged: bool
    notification_deadline_date: date | None
    total_eligible_hours: Decimal
    total_eligible_wage_delta: Decimal
    total_eligible_hw_delta: Decimal
    total_accompanying_taxes_wc: Decimal
    voluntary_raise_excluded_amount: Decimal
    overhead_excluded_amount: Decimal = Decimal("0.00")
    ga_excluded_amount: Decimal = Decimal("0.00")
    profit_excluded_amount: Decimal = Decimal("0.00")
    total_claim_amount: Decimal
    gate_reason: str
    ledger_lines: list[LedgerLineResult] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpanSchema] = Field(default_factory=list)


class CalculatorRequest(_CompatBaseModel):
    contract_piid: str = "47PM0924C0012"
    worker_count: int = Field(default=25, ge=1, le=5000)
    annual_hours_per_worker: Decimal = Decimal("2080")
    w_prev: Decimal = Decimal("16.50")
    w_req_new: Decimal = Decimal("18.20")
    w_act_new: Decimal = Decimal("18.50")
    hw_prev: Decimal = Decimal("4.57")
    hw_req_new: Decimal = Decimal("4.98")
    hw_act_new: Decimal = Decimal("4.98")
    fica_rate: Decimal = Decimal("0.0765")
    futa_rate: Decimal = Decimal("0.0060")
    suta_rate: Decimal = Decimal("0.0210")
    workers_comp_rate: Decimal = Decimal("0.0315")

    @compat_validator(
        "annual_hours_per_worker",
        "w_prev",
        "w_req_new",
        "w_act_new",
        "hw_prev",
        "hw_req_new",
        "hw_act_new",
        "fica_rate",
        "futa_rate",
        "suta_rate",
        "workers_comp_rate",
    )
    @classmethod
    def validate_dec(cls, v: Any) -> Decimal:
        return _reject_float(v)
