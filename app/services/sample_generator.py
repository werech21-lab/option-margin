"""Sample audits and CAN-SPAM prospect copy. These are illustrations, not entitlements."""

from __future__ import annotations

from decimal import Decimal

from app.config import RULE_PACK_VERSION, money_text, q2, q4

POSTAL_ADDRESS = "OptionMargin, 1200 Wilson Boulevard, Suite 300, Arlington, VA 22209"


def demo_case_contract() -> dict[str, object]:
    return {
        "case_id": "CASE-DEMO-017",
        "contract_id": "CONTRACT-DEMO",
        "status": "POTENTIAL",
        "event_type": "WAGE_REVISION",
        "estimated_monthly_exposure_usd": "9600.00",
        "evidence_complete": False,
        "missing_fields": ["verified_receipt_date", "applicable_contract_modification"],
        "next_action": "Complete evidence package",
        "rule_pack_version": RULE_PACK_VERSION,
    }


def sensitivity_per_10000_hours(hourly_delta: Decimal | str | int) -> Decimal:
    """Dollar sensitivity for 10,000 eligible hours. This is not a legal entitlement."""
    return q2(q4(hourly_delta) * Decimal("10000"))


def illustrative_eighty_cent_sensitivity() -> Decimal:
    return sensitivity_per_10000_hours(Decimal("0.80"))


def cold_email(*, company: str, award_id: str, agency: str, county: str, state: str, hourly_delta: Decimal) -> str:
    sensitivity = money_text(sensitivity_per_10000_hours(hourly_delta))
    baseline = money_text(illustrative_eighty_cent_sensitivity())
    return (
        f"Subject: Advertisement — wage determination illustration for award {award_id}\n\n"
        f"Hello {company},\n\n"
        "This is an advertisement from OptionMargin. It is not a legal determination, "
        "not a notice from a contracting officer, and not a statement that your firm is "
        "entitled to a price adjustment.\n\n"
        f"Public award {award_id} ({agency}) shows place of performance in {county}, {state}, "
        f"NAICS 561720. Using the matched area wage determination, an hourly delta of "
        f"${q4(hourly_delta)} across 10,000 eligible hours illustrates {sensitivity}. "
        f"A separate $0.80 per hour illustration equals {baseline} per 10,000 hours. "
        "FAR 52.222-43 recovery still requires an incorporated SF-30, a verified receipt "
        "date, and Zero-PII payroll. Overhead, G&A, and profit are not part of the clause.\n\n"
        f"{POSTAL_ADDRESS}\n"
        "To opt out, reply with the subject UNSUBSCRIBE or open /unsubscribe on this site.\n"
    )
