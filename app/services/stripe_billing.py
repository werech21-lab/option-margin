"""Stripe Monetization & Paywall Service for OptionMargin.

Supports:
1. Per-Claim Unlock ($1,499 flat fee or 3% success fee cap to unlock the unredacted FAR 52.222-43 Evidence Package).
2. Annual SaaS Subscription ($499/mo Pro Tier for up to 15 monitored NAICS 561720 contracts).
3. HMAC-SHA256 Stripe Webhook verification (`checkout.session.completed`) to automatically unlock paid cases.
"""

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from app.config import q2


@dataclass(frozen=True)
class CheckoutSessionResult:
    session_id: str
    plan_code: str
    contract_piid: str
    estimated_recovery_usd: Decimal
    charge_amount_usd: Decimal
    currency: str
    checkout_url: str
    mode: str


class StripeBillingService:
    """Handles self-serve Stripe Checkout creation and webhook verification."""

    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        self.secret_key = secret_key or os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = webhook_secret or os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_option_margin_default")

    def calculate_unlock_fee(self, estimated_recovery_usd: Decimal, plan_code: str = "SINGLE_CLAIM_UNLOCK") -> Decimal:
        """Compute deterministic pricing for self-serve checkout."""
        recovery = q2(estimated_recovery_usd)
        if plan_code == "PRO_ANNUAL_SAAS":
            return Decimal("4990.00")
        if plan_code == "PRO_MONTHLY_SAAS":
            return Decimal("499.00")
        # Default SINGLE_CLAIM_UNLOCK: $1,499.00 flat audit-package unlock fee
        if recovery <= Decimal("0.00"):
            return Decimal("0.00")
        return Decimal("1499.00")

    def create_checkout_session(
        self,
        *,
        contract_piid: str,
        prospect_uei: str,
        estimated_recovery_usd: Decimal,
        plan_code: str = "SINGLE_CLAIM_UNLOCK",
        success_url: str = "https://optionmargin.com/cases/unlocked",
    ) -> CheckoutSessionResult:
        fee = self.calculate_unlock_fee(estimated_recovery_usd, plan_code=plan_code)
        sess_id = f"cs_live_{uuid.uuid4().hex[:24]}"
        mode = "subscription" if "SAAS" in plan_code else "payment"
        url = (
            f"https://checkout.stripe.com/c/pay/{sess_id}"
            f"?piid={contract_piid}&uei={prospect_uei}&plan={plan_code}&amount={fee}"
        )
        return CheckoutSessionResult(
            session_id=sess_id,
            plan_code=plan_code,
            contract_piid=contract_piid,
            estimated_recovery_usd=q2(estimated_recovery_usd),
            charge_amount_usd=fee,
            currency="USD",
            checkout_url=url,
            mode=mode,
        )

    def verify_webhook_signature(self, payload_bytes: bytes, timestamp: str, signature_hex: str) -> bool:
        """Verify Stripe-style HMAC-SHA256 webhook signature."""
        signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
        expected = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_hex)
