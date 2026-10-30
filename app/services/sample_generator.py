"""Self-Selling Acquisition Loop Service (`task_type = "prospect_audit"`).

Combines public USAspending NAICS 561720 contract awards with public SAM.gov
Wage Determination revisions to generate a watermarked, zero-touch Prospect Margin Bleed Teaser.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from app.config import q2, q4


@dataclass(frozen=True)
class ProspectAuditTeaser:
    task_type: str
    prospect_company_name: str
    prospect_uei: str
    contract_piid: str
    agency_name: str
    locality: str
    wd_number: str
    old_revision: int
    new_revision: int
    next_option_date: date
    days_until_option: int
    estimated_janitor_fte: int
    old_wd_rate: Decimal
    new_wd_rate: Decimal
    old_hw_rate: Decimal
    new_hw_rate: Decimal
    estimated_annual_recovery_usd: Decimal
    redacted_evidence_preview: str
    claim_unlock_cta_url: str


class SampleGenerator:
    """Generates automated, zero-touch prospect audit packets for PLG customer acquisition."""

    TASK_TYPE = "prospect_audit"

    def build_prospect_audit(
        self,
        prospect_company_name: str,
        prospect_uei: str,
        contract_piid: str,
        agency_name: str,
        locality: str,
        wd_number: str,
        old_revision: int,
        new_revision: int,
        next_option_date: date,
        old_wd_rate: Decimal,
        new_wd_rate: Decimal,
        old_hw_rate: Decimal,
        new_hw_rate: Decimal,
        estimated_janitor_fte: int = 24,
        as_of_date: date | None = None,
    ) -> ProspectAuditTeaser:
        ref_date = as_of_date or date(2026, 10, 30)
        days_to_opt = (next_option_date - ref_date).days

        w_delta = max(Decimal("0.0000"), q4(new_wd_rate) - q4(old_wd_rate))
        hw_delta = max(Decimal("0.0000"), q4(new_hw_rate) - q4(old_hw_rate))
        statutory_tax_factor = Decimal("0.1350")  # FICA 7.65% + FUTA 0.60% + SUTA 2.10% + WC 3.15%
        tax_delta = q4(w_delta * statutory_tax_factor)

        hourly_total = w_delta + hw_delta + tax_delta
        total_hours = Decimal(str(estimated_janitor_fte)) * Decimal("2080")
        annual_recovery = q2(hourly_total * total_hours)

        preview = (
            f"[WATERMARKED PROSPECT AUDIT — {prospect_company_name} ({prospect_uei})] "
            f"Contract {contract_piid} ({agency_name}) in {locality} is {days_to_opt} days from Option Exercise "
            f"({next_option_date.isoformat()}). SAM.gov WD {wd_number} increased from Rev {old_revision} "
            f"(${old_wd_rate}/hr + ${old_hw_rate} H&W) to Rev {new_revision} (${new_wd_rate}/hr + ${new_hw_rate} H&W). "
            f"Estimated FAR 52.222-43 Annual Price Adjustment Entitlement: ${annual_recovery:,.2f} "
            f"(Strict 0.00% OH/G&A/Profit applied). Upload SF-30 Mod [REDACTED] to unlock SF-1411 / Claim Narrative."
        )

        return ProspectAuditTeaser(
            task_type=self.TASK_TYPE,
            prospect_company_name=prospect_company_name,
            prospect_uei=prospect_uei,
            contract_piid=contract_piid,
            agency_name=agency_name,
            locality=locality,
            wd_number=wd_number,
            old_revision=old_revision,
            new_revision=new_revision,
            next_option_date=next_option_date,
            days_until_option=days_to_opt,
            estimated_janitor_fte=estimated_janitor_fte,
            old_wd_rate=q4(old_wd_rate),
            new_wd_rate=q4(new_wd_rate),
            old_hw_rate=q4(old_hw_rate),
            new_hw_rate=q4(new_hw_rate),
            estimated_annual_recovery_usd=annual_recovery,
            redacted_evidence_preview=preview,
            claim_unlock_cta_url=f"/claim-audit/{contract_piid}?uei={prospect_uei}",
        )
