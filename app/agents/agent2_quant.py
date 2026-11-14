"""Agent 2 — Quant.

FAR 52.222-43 arithmetic is Decimal-only. Overhead, G&A, and profit are forced
to zero and asserted on every calculation. A public wage increase without a
verified receipt date or an applicable SF-30 stays POTENTIAL. A modification
without usable payroll stays INSUFFICIENT_DATA. SUPPORTED is reached only when
the public WD, the SF-30, the receipt date, and Zero-PII payroll are all present.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.config import RULE_PACK_VERSION, ZERO, ZERO_2, ZERO_4, q2, q4
from app.models import AdjustmentCase, CalculationVersion, utcnow
from app.schemas import CaseContract, GateAssessment, HourlyComponents, PriceAdjustment

MISSING_RECEIPT = "verified_receipt_date"
MISSING_MOD = "applicable_contract_modification"


class Agent2Quant:
    """Deterministic price-adjustment engine and fail-closed state gate."""

    def hourly_components(
        self,
        *,
        actual_prev_wage: Decimal | str | int,
        new_required_wage: Decimal | str | int,
        actual_new_wage: Decimal | str | int,
        actual_prev_hw: Decimal | str | int = ZERO,
        new_required_hw: Decimal | str | int = ZERO,
        actual_new_hw: Decimal | str | int = ZERO,
        hw_delta: Decimal | str | int | None = None,
        fica_rate: Decimal | str | int = ZERO,
        futa_rate: Decimal | str | int = ZERO,
        suta_rate: Decimal | str | int = ZERO,
        wc_rate: Decimal | str | int = ZERO,
    ) -> HourlyComponents:
        eligible_wage_delta, voluntary_wage_stripped = _eligible_and_voluntary(
            actual_prev_wage, new_required_wage, actual_new_wage
        )
        if hw_delta is None:
            eligible_hw_delta, voluntary_hw_stripped = _eligible_and_voluntary(
                actual_prev_hw, new_required_hw, actual_new_hw
            )
        else:
            eligible_hw_delta = q4(max(ZERO, Decimal(q4(hw_delta))))
            voluntary_hw_stripped = ZERO_4
        tax_rate_total = q4(q4(fica_rate) + q4(futa_rate) + q4(suta_rate) + q4(wc_rate))
        tax_per_hour = q4(eligible_wage_delta * tax_rate_total)
        overhead = q2(0)
        ga = q2(0)
        profit = q2(0)
        assert overhead == 0 and ga == 0 and profit == 0
        per_hour = q4(eligible_wage_delta + eligible_hw_delta + tax_per_hour)
        return HourlyComponents(
            eligible_wage_delta=eligible_wage_delta,
            voluntary_wage_stripped=voluntary_wage_stripped,
            eligible_hw_delta=eligible_hw_delta,
            voluntary_hw_stripped=voluntary_hw_stripped,
            tax_rate_total=tax_rate_total,
            tax_per_hour=tax_per_hour,
            overhead=overhead,
            ga=ga,
            profit=profit,
            per_hour_entitlement=per_hour,
        )

    def compute_adjustment(
        self,
        *,
        workers: int = 1,
        hours_per_worker: Decimal | str | int = ZERO,
        total_hours: Decimal | str | int | None = None,
        actual_prev_wage: Decimal | str | int,
        new_required_wage: Decimal | str | int,
        actual_new_wage: Decimal | str | int,
        actual_prev_hw: Decimal | str | int = ZERO,
        new_required_hw: Decimal | str | int = ZERO,
        actual_new_hw: Decimal | str | int = ZERO,
        hw_delta: Decimal | str | int | None = None,
        fica_rate: Decimal | str | int = ZERO,
        futa_rate: Decimal | str | int = ZERO,
        suta_rate: Decimal | str | int = ZERO,
        wc_rate: Decimal | str | int = ZERO,
    ) -> PriceAdjustment:
        if workers < 0:
            raise ValueError("Worker count cannot be negative.")
        hourly = self.hourly_components(
            actual_prev_wage=actual_prev_wage,
            new_required_wage=new_required_wage,
            actual_new_wage=actual_new_wage,
            actual_prev_hw=actual_prev_hw,
            new_required_hw=new_required_hw,
            actual_new_hw=actual_new_hw,
            hw_delta=hw_delta,
            fica_rate=fica_rate,
            futa_rate=futa_rate,
            suta_rate=suta_rate,
            wc_rate=wc_rate,
        )
        hours = q2(total_hours) if total_hours is not None else q2(Decimal(workers) * q2(hours_per_worker))
        if hours < 0:
            raise ValueError("Hours cannot be negative.")
        monthly_base = q2(hours * hourly.eligible_wage_delta)
        monthly_hw = q2(hours * hourly.eligible_hw_delta)
        monthly_tax = q2(hours * hourly.tax_per_hour)
        monthly_total = q2(monthly_base + monthly_hw + monthly_tax)
        annualized = q2(monthly_total * Decimal(12))
        return PriceAdjustment(
            eligible_wage_delta=hourly.eligible_wage_delta,
            voluntary_wage_stripped=hourly.voluntary_wage_stripped,
            eligible_hw_delta=hourly.eligible_hw_delta,
            voluntary_hw_stripped=hourly.voluntary_hw_stripped,
            tax_rate_total=hourly.tax_rate_total,
            tax_per_hour=hourly.tax_per_hour,
            overhead=hourly.overhead,
            ga=hourly.ga,
            profit=hourly.profit,
            per_hour_entitlement=hourly.per_hour_entitlement,
            total_workers=workers,
            total_hours=hours,
            monthly_base_entitlement_usd=monthly_base,
            monthly_hw_entitlement_usd=monthly_hw,
            monthly_tax_entitlement_usd=monthly_tax,
            total_monthly_entitlement_usd=monthly_total,
            annualized_exposure_usd=annualized,
        )

    def price_split_hours(
        self,
        rows: list[dict[str, object]],
    ) -> dict[str, PriceAdjustment]:
        """Price each contract from its own hours. The same worker_hash may appear on both."""
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            contract_id = str(row["contract_id"])
            grouped.setdefault(contract_id, []).append(row)
        priced: dict[str, PriceAdjustment] = {}
        for contract_id, group in grouped.items():
            hours = q2(sum((q2(item["hours"]) for item in group), ZERO_2))
            first = group[0]
            hashes = {str(item["worker_hash"]) for item in group}
            if len(hashes) != 1:
                raise ValueError(f"Contract {contract_id} mixed worker hashes inside one split group.")
            priced[contract_id] = self.compute_adjustment(
                workers=1,
                total_hours=hours,
                actual_prev_wage=Decimal(str(first["actual_prev_wage"])),
                new_required_wage=Decimal(str(first["new_required_wage"])),
                actual_new_wage=Decimal(str(first["actual_new_wage"])),
                actual_prev_hw=Decimal(str(first.get("actual_prev_hw", "0"))),
                new_required_hw=Decimal(str(first.get("new_required_hw", "0"))),
                actual_new_hw=Decimal(str(first.get("actual_new_hw", "0"))),
                fica_rate=Decimal(str(first.get("fica_rate", "0"))),
                futa_rate=Decimal(str(first.get("futa_rate", "0"))),
                suta_rate=Decimal(str(first.get("suta_rate", "0"))),
                wc_rate=Decimal(str(first.get("wc_rate", "0"))),
            )
        for contract_id, adjustment in priced.items():
            own_hours = q2(sum((q2(item["hours"]) for item in grouped[contract_id]), ZERO_2))
            if adjustment.total_hours != own_hours:
                raise RuntimeError(f"Contract {contract_id} hours do not match its own payroll rows.")
        return priced

    def assess_case(
        self,
        *,
        monitored: bool = True,
        rates_changed: bool = True,
        formatting_only: bool = False,
        is_cba: bool = False,
        variable_fringe: bool = False,
        has_sf30: bool = False,
        verified_receipt_date: date | None = None,
        payroll_rows_present: bool = False,
        payroll_contradictory: bool = False,
        mapping_missing: bool = False,
        option_within_90_days: bool = False,
        public_wd_increase: bool = True,
    ) -> GateAssessment:
        deadline = None
        if verified_receipt_date is not None:
            deadline = verified_receipt_date + timedelta(days=30)
        if not monitored:
            return self._gate(
                status="ARCHIVE",
                gate_decision="ARCHIVE",
                event_type="WAGE_REVISION",
                evidence_complete=False,
                missing_fields=["monitored_contract"],
                next_action="No adjustment case opened",
                verified_receipt_date=verified_receipt_date,
                filing_deadline_date=None,
                opens_case=False,
            )
        if formatting_only or not rates_changed:
            return self._gate(
                status="IGNORE",
                gate_decision="IGNORE",
                event_type="WAGE_REVISION",
                evidence_complete=False,
                missing_fields=[],
                next_action="No adjustment case opened",
                verified_receipt_date=verified_receipt_date,
                filing_deadline_date=None,
                opens_case=False,
            )
        if is_cba or variable_fringe:
            return self._gate(
                status="INSUFFICIENT_DATA",
                gate_decision="ANALYZE",
                event_type="WAGE_REVISION",
                evidence_complete=False,
                missing_fields=["supported_scope"],
                next_action="UNSUPPORTED_SCOPE: CBA or variable fringe is outside rule pack US-SCLS-1.0",
                verified_receipt_date=verified_receipt_date,
                filing_deadline_date=deadline,
                opens_case=True,
                unsupported_scope=True,
            )
        missing: list[str] = []
        if verified_receipt_date is None:
            missing.append(MISSING_RECEIPT)
        if not has_sf30:
            missing.append(MISSING_MOD)
        if missing:
            if option_within_90_days:
                event_type = "OPTION_PERIOD_ALERT"
                next_action = "Upcoming Option Period Exposure"
            else:
                event_type = "WAGE_REVISION"
                next_action = "Complete evidence package"
            return self._gate(
                status="POTENTIAL",
                gate_decision="ANALYZE",
                event_type=event_type,
                evidence_complete=False,
                missing_fields=missing,
                next_action=next_action,
                verified_receipt_date=verified_receipt_date,
                filing_deadline_date=None,
                opens_case=True,
            )
        if (not payroll_rows_present) or payroll_contradictory or mapping_missing:
            gaps = []
            if not payroll_rows_present:
                gaps.append("payroll_rows")
            if payroll_contradictory:
                gaps.append("payroll_contradiction")
            if mapping_missing:
                gaps.append("occupation_mapping")
            return self._gate(
                status="INSUFFICIENT_DATA",
                gate_decision="ANALYZE",
                event_type="WAGE_REVISION",
                evidence_complete=False,
                missing_fields=gaps,
                next_action="Upload Zero-PII payroll rows before any claim amount is treated as supported",
                verified_receipt_date=verified_receipt_date,
                filing_deadline_date=deadline,
                opens_case=True,
            )
        return self._gate(
            status="SUPPORTED",
            gate_decision="ANALYZE",
            event_type="OPTION_PERIOD_ALERT" if option_within_90_days and not public_wd_increase else "WAGE_REVISION",
            evidence_complete=True,
            missing_fields=[],
            next_action="Prepare FAR 52.222-43 price adjustment claim package",
            verified_receipt_date=verified_receipt_date,
            filing_deadline_date=deadline,
            opens_case=True,
        )

    def case_contract(
        self,
        *,
        case_id: str,
        contract_id: str,
        assessment: GateAssessment,
        monthly: Decimal,
    ) -> dict[str, object]:
        document = CaseContract(
            case_id=case_id,
            contract_id=contract_id,
            status=assessment.status,
            event_type=assessment.event_type,
            estimated_monthly_exposure_usd=f"{q2(monthly):.2f}",
            evidence_complete=assessment.evidence_complete,
            missing_fields=list(assessment.missing_fields),
            next_action=assessment.next_action,
            rule_pack_version=assessment.rule_pack_version,
        )
        return document.model_dump()

    def create_case_with_calculation(
        self,
        session,
        *,
        tenant_id: str,
        case_id: str,
        contract_id: str,
        adjustment: PriceAdjustment,
        breakdown: dict,
        status: str,
        event_type: str,
        evidence_complete: bool,
        missing_fields: list[str],
        next_action: str,
        verified_receipt_date: date | None = None,
        filing_deadline_date: date | None = None,
        change_event_id: str | None = None,
        agreed_adjustment_usd: Decimal = ZERO_2,
        billed_collected_usd: Decimal = ZERO_2,
    ) -> CalculationVersion:
        case = AdjustmentCase(
            tenant_id=tenant_id,
            case_id=case_id,
            contract_id=contract_id,
            change_event_id=change_event_id,
            status=status,
            event_type=event_type,
            estimated_monthly_exposure_usd=adjustment.total_monthly_entitlement_usd,
            annualized_exposure_usd=adjustment.annualized_exposure_usd,
            agreed_adjustment_usd=agreed_adjustment_usd,
            billed_collected_usd=billed_collected_usd,
            unbilled_leakage_usd=ZERO_2,
            evidence_complete=evidence_complete,
            missing_fields_json=list(missing_fields),
            next_action=next_action,
            verified_receipt_date=verified_receipt_date,
            filing_deadline_date=filing_deadline_date,
            rule_pack_version=RULE_PACK_VERSION,
            updated_at=utcnow(),
        )
        session.add(case)
        session.flush()
        version = self._version_row(
            tenant_id=tenant_id,
            case_id=case_id,
            version_num=1,
            adjustment=adjustment,
            breakdown=breakdown,
        )
        session.add(version)
        session.flush()
        return version

    def apply_correcting_revision(
        self,
        session,
        *,
        case_id: str,
        correcting_revision: int,
        new_required_wage: Decimal | str | int,
        new_required_hw: Decimal | str | int | None = None,
        actual_new_wage: Decimal | str | int | None = None,
    ) -> CalculationVersion:
        """Recalculate against the stored baseline and append the next version number."""
        prior = (
            session.query(CalculationVersion)
            .filter(CalculationVersion.case_id == case_id)
            .order_by(CalculationVersion.version_num.desc())
            .first()
        )
        if prior is None:
            raise LookupError(f"No calculation baseline exists for {case_id}.")
        data = dict(prior.breakdown_json)
        required_hw = new_required_hw if new_required_hw is not None else data["new_required_hw"]
        new_actual = actual_new_wage if actual_new_wage is not None else data["actual_new_wage"]
        adjustment = self.compute_adjustment(
            workers=int(data["workers"]),
            total_hours=Decimal(str(data["total_hours"])),
            actual_prev_wage=Decimal(str(data["actual_prev_wage"])),
            new_required_wage=new_required_wage,
            actual_new_wage=new_actual,
            actual_prev_hw=Decimal(str(data["actual_prev_hw"])),
            new_required_hw=required_hw,
            actual_new_hw=Decimal(str(data["actual_new_hw"])),
            fica_rate=Decimal(str(data["fica_rate"])),
            futa_rate=Decimal(str(data["futa_rate"])),
            suta_rate=Decimal(str(data["suta_rate"])),
            wc_rate=Decimal(str(data["wc_rate"])),
        )
        data["new_required_wage"] = f"{q4(new_required_wage):.4f}"
        data["new_required_hw"] = f"{q4(required_hw):.4f}"
        data["actual_new_wage"] = f"{q4(new_actual):.4f}"
        data["revision"] = correcting_revision
        data["overhead"] = "0.00"
        data["ga"] = "0.00"
        data["profit"] = "0.00"
        version = self._version_row(
            tenant_id=prior.tenant_id,
            case_id=case_id,
            version_num=prior.version_num + 1,
            adjustment=adjustment,
            breakdown=data,
        )
        session.add(version)
        case = session.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one()
        case.estimated_monthly_exposure_usd = adjustment.total_monthly_entitlement_usd
        case.annualized_exposure_usd = adjustment.annualized_exposure_usd
        case.updated_at = utcnow()
        session.flush()
        return version

    def _version_row(
        self,
        *,
        tenant_id: str,
        case_id: str,
        version_num: int,
        adjustment: PriceAdjustment,
        breakdown: dict,
    ) -> CalculationVersion:
        return CalculationVersion(
            tenant_id=tenant_id,
            case_id=case_id,
            version_num=version_num,
            total_workers=adjustment.total_workers,
            total_monthly_hours=adjustment.total_hours,
            mandatory_wage_delta=adjustment.eligible_wage_delta,
            voluntary_wage_stripped=adjustment.voluntary_wage_stripped,
            mandatory_hw_delta=adjustment.eligible_hw_delta,
            accompanying_tax_hourly=adjustment.tax_per_hour,
            monthly_base_entitlement_usd=adjustment.monthly_base_entitlement_usd,
            monthly_hw_entitlement_usd=adjustment.monthly_hw_entitlement_usd,
            monthly_tax_entitlement_usd=adjustment.monthly_tax_entitlement_usd,
            total_monthly_entitlement_usd=adjustment.total_monthly_entitlement_usd,
            breakdown_json=breakdown,
            computed_at=utcnow(),
        )

    def _gate(self, **kwargs: object) -> GateAssessment:
        payload = dict(kwargs)
        payload["rule_pack_version"] = RULE_PACK_VERSION
        return GateAssessment(**payload)  # type: ignore[arg-type]


def breakdown_document(
    *,
    adjustment: PriceAdjustment,
    revision: int,
    actual_prev_wage: Decimal | str | int,
    new_required_wage: Decimal | str | int,
    actual_new_wage: Decimal | str | int,
    actual_prev_hw: Decimal | str | int = ZERO,
    new_required_hw: Decimal | str | int = ZERO,
    actual_new_hw: Decimal | str | int = ZERO,
    fica_rate: Decimal | str | int = ZERO,
    futa_rate: Decimal | str | int = ZERO,
    suta_rate: Decimal | str | int = ZERO,
    wc_rate: Decimal | str | int = ZERO,
    hours_per_worker: Decimal | str | int = ZERO,
) -> dict[str, object]:
    return {
        "workers": adjustment.total_workers,
        "hours_per_worker": f"{q2(hours_per_worker):.2f}",
        "total_hours": f"{adjustment.total_hours:.2f}",
        "actual_prev_wage": f"{q4(actual_prev_wage):.4f}",
        "new_required_wage": f"{q4(new_required_wage):.4f}",
        "actual_new_wage": f"{q4(actual_new_wage):.4f}",
        "actual_prev_hw": f"{q4(actual_prev_hw):.4f}",
        "new_required_hw": f"{q4(new_required_hw):.4f}",
        "actual_new_hw": f"{q4(actual_new_hw):.4f}",
        "fica_rate": f"{q4(fica_rate):.4f}",
        "futa_rate": f"{q4(futa_rate):.4f}",
        "suta_rate": f"{q4(suta_rate):.4f}",
        "wc_rate": f"{q4(wc_rate):.4f}",
        "revision": revision,
        "overhead": "0.00",
        "ga": "0.00",
        "profit": "0.00",
        "rule_pack_version": RULE_PACK_VERSION,
    }


def _eligible_and_voluntary(
    prev_actual: Decimal | str | int,
    required: Decimal | str | int,
    actual_new: Decimal | str | int,
) -> tuple[Decimal, Decimal]:
    previous = q4(prev_actual)
    required_rate = q4(required)
    new_rate = q4(actual_new)
    if previous >= required_rate:
        eligible = ZERO_4
    else:
        eligible = q4(max(ZERO, min(new_rate, required_rate) - previous))
    voluntary = q4(max(ZERO, new_rate - required_rate))
    return eligible, voluntary
