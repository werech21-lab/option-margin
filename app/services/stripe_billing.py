"""Stripe Monetization, Real API Checkout & Self-Hosted Corporate Invoice Fallback."""

import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
import urllib.error
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
    """Handles self-serve Stripe Checkout creation (real Stripe API + self-hosted fallback)."""

    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        self.secret_key = (secret_key or os.getenv("STRIPE_SECRET_KEY", "")).strip()
        self.webhook_secret = webhook_secret or os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_option_margin_default")
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "https://optionmargin-engine.onrender.com").rstrip("/")

    def calculate_unlock_fee(self, estimated_recovery_usd: Decimal, plan_code: str = "SINGLE_CLAIM_UNLOCK") -> Decimal:
        recovery = q2(estimated_recovery_usd)
        if plan_code == "PRO_ANNUAL_SAAS":
            return Decimal("4990.00")
        if plan_code == "PRO_MONTHLY_SAAS":
            return Decimal("499.00")
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
        success_url: str | None = None,
    ) -> CheckoutSessionResult:
        fee = self.calculate_unlock_fee(estimated_recovery_usd, plan_code=plan_code)
        recovery = q2(estimated_recovery_usd)
        sess_id = f"cs_live_{uuid.uuid4().hex[:24]}"
        mode = "subscription" if "SAAS" in plan_code else "payment"
        final_success_url = success_url or f"{self.public_base_url}/command-center?unlocked={contract_piid}"

        # If a real Stripe Secret Key is configured, call https://api.stripe.com/v1/checkout/sessions
        if self.secret_key.startswith(("sk_live_", "sk_test_")):
            try:
                form_data = {
                    "mode": "payment",
                    "success_url": final_success_url,
                    "cancel_url": f"{self.public_base_url}/claim-audit/{contract_piid}?uei={prospect_uei}",
                    "client_reference_id": f"{contract_piid}:{prospect_uei}",
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][unit_amount]": str(int(fee * 100)),
                    "line_items[0][price_data][product_data][name]": f"FAR 52.222-43 Evidence Package Unlock ({contract_piid})",
                    "line_items[0][price_data][product_data][description]": f"Verified SCLS Price Adjustment Audit for {contract_piid} (Est. Recovery ${recovery:,.2f})",
                    "line_items[0][quantity]": "1",
                }
                encoded = urllib.parse.urlencode(form_data).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.stripe.com/v1/checkout/sessions",
                    data=encoded,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {self.secret_key}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    stripe_data = json.loads(resp.read().decode("utf-8"))
                    if stripe_data.get("url"):
                        return CheckoutSessionResult(
                            session_id=stripe_data.get("id", sess_id),
                            plan_code=plan_code,
                            contract_piid=contract_piid,
                            estimated_recovery_usd=recovery,
                            charge_amount_usd=fee,
                            currency="USD",
                            checkout_url=stripe_data["url"],
                            mode=mode,
                        )
            except Exception:
                pass

        # Self-hosted high-converting Checkout & Corporate Invoice Capture Portal on our own domain
        query = urllib.parse.urlencode(
            {
                "piid": contract_piid,
                "uei": prospect_uei,
                "plan": plan_code,
                "amount": str(fee),
                "recovery": str(recovery),
            }
        )
        url = f"{self.public_base_url}/checkout/{sess_id}?{query}"
        return CheckoutSessionResult(
            session_id=sess_id,
            plan_code=plan_code,
            contract_piid=contract_piid,
            estimated_recovery_usd=recovery,
            charge_amount_usd=fee,
            currency="USD",
            checkout_url=url,
            mode=mode,
        )

    def verify_webhook_signature(self, payload_bytes: bytes, timestamp: str, signature_hex: str) -> bool:
        signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
        expected = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_hex)
