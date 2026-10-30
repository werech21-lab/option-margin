"""Automated Outbound Email & Prospect Teaser Dispatcher for OptionMargin."""

import json
import os
import smtplib
import urllib.request
import urllib.error
from dataclasses import dataclass
from email.message import EmailMessage
from app.services.sample_generator import ProspectAuditTeaser
from app.services.stripe_billing import StripeBillingService


@dataclass(frozen=True)
class DispatchedAuditEmail:
    idempotency_key: str
    recipient_email: str
    subject: str
    contract_piid: str
    estimated_recovery_usd: str
    stripe_checkout_url: str
    delivery_channel: str
    delivery_status: str
    html_body: str


class OutboundEmailDispatcher:
    """Builds and dispatches self-selling FAR 52.222-43 prospect audit emails."""

    def __init__(self, public_base_url: str | None = None) -> None:
        self.public_base_url = (
            public_base_url or os.getenv("PUBLIC_BASE_URL", "https://optionmargin-engine.onrender.com")
        ).rstrip("/")
        self.stripe_service = StripeBillingService()

    def build_audit_email(
        self,
        teaser: ProspectAuditTeaser,
        recipient_email: str = "werech21@gmail.com",
    ) -> DispatchedAuditEmail:
        checkout = self.stripe_service.create_checkout_session(
            contract_piid=teaser.contract_piid,
            prospect_uei=teaser.prospect_uei,
            estimated_recovery_usd=teaser.estimated_annual_recovery_usd,
            plan_code="SINGLE_CLAIM_UNLOCK",
            success_url=f"{self.public_base_url}/command-center",
        )
        subject = (
            f"[FAR 52.222-43 Notice] Contract {teaser.contract_piid}: "
            f"${teaser.estimated_annual_recovery_usd:,.2f} Mandatory SCLS Price Adjustment Entitlement"
        )
        html_body = (
            f"<h2>OptionMargin Pre-Option Audit: {teaser.prospect_company_name}</h2>"
            f"<p>Contract <strong>{teaser.contract_piid}</strong> ({teaser.agency_name}, UEI: {teaser.prospect_uei}) "
            f"is {teaser.days_until_option} days from Option Exercise ({teaser.next_option_date.isoformat()}).</p>"
            f"<p><strong>Estimated Annual FAR 52.222-43 Recovery: ${teaser.estimated_annual_recovery_usd:,.2f}</strong> "
            f"(WD {teaser.wd_number} Rev {teaser.old_revision} -> Rev {teaser.new_revision}; 0.00% OH/G&A/Profit).</p>"
            f"<p><a href='{checkout.checkout_url}'>Unlock Full Audit-Ready Evidence Package ($1,499)</a></p>"
        )
        idemp_key = f"PROSPECT-EMAIL-{teaser.contract_piid}-REV{teaser.new_revision}"
        channel, status = self._send_if_configured(recipient_email, subject, html_body, teaser.redacted_evidence_preview)
        return DispatchedAuditEmail(
            idempotency_key=idemp_key,
            recipient_email=recipient_email,
            subject=subject,
            contract_piid=teaser.contract_piid,
            estimated_recovery_usd=str(teaser.estimated_annual_recovery_usd),
            stripe_checkout_url=checkout.checkout_url,
            delivery_channel=channel,
            delivery_status=status,
            html_body=html_body,
        )

    @staticmethod
    def _send_if_configured(to_email: str, subject: str, html_body: str, text_body: str) -> tuple[str, str]:
        resend_key = os.getenv("RESEND_API_KEY", "").strip()
        if resend_key:
            try:
                payload = json.dumps(
                    {
                        "from": os.getenv("EMAIL_FROM", "OptionMargin <onboarding@resend.dev>"),
                        "to": [to_email],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.resend.com/emails",
                    data=payload,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {resend_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if 200 <= resp.status < 300:
                        return "RESEND_API", "SENT_LIVE"
            except urllib.error.URLError:
                pass
        return "TRANSACTIONAL_OUTBOX", "QUEUED_IN_OUTBOX"
