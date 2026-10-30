"""Automated Outbound Email & Prospect Teaser Dispatcher for OptionMargin."""

import html
import json
import os
import smtplib
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from email.message import EmailMessage
from app.services.poc_resolver import ContractorPOC
from app.services.sample_generator import ProspectAuditTeaser
from app.services.stripe_billing import StripeBillingService

AUDIT_INBOX = "werech21@gmail.com"


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
        recipient_email: str = AUDIT_INBOX,
        poc: ContractorPOC | None = None,
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
        company = html.escape(teaser.prospect_company_name)
        agency = html.escape(teaser.agency_name)
        checkout_url = html.escape(checkout.checkout_url, quote=True)
        poc_html = ""
        poc_text = ""
        if poc is not None:
            mailto, gmail_url = _compose_links(
                poc.poc_email,
                subject,
                (
                    f"Contract {teaser.contract_piid} estimated FAR 52.222-43 recovery "
                    f"${teaser.estimated_annual_recovery_usd:,.2f}. "
                    f"Unlock the evidence package: {checkout.checkout_url}"
                ),
            )
            note = (
                "SAM.gov published this electronic address."
                if poc.resolution_source == "SAM_GOV_ENTITY_API"
                else "Desk suggestion only. This notice was delivered to the OptionMargin audit inbox, not to that address."
            )
            poc_html = (
                f"<p><strong>Contracts desk:</strong> {html.escape(poc.poc_name)} "
                f"({html.escape(poc.poc_title)}) &lt;{html.escape(poc.poc_email)}&gt;<br>"
                f"Source: {html.escape(poc.resolution_source)}. {html.escape(note)}</p>"
                f"<p><a href='{html.escape(mailto, quote=True)}'>Email this contracts desk</a> · "
                f"<a href='{html.escape(gmail_url, quote=True)}'>Send via Gmail</a></p>"
            )
            poc_text = (
                f"Contracts desk: {poc.poc_name} ({poc.poc_title}) <{poc.poc_email}> "
                f"[{poc.resolution_source}]. {note} Gmail: {gmail_url}"
            )
        html_body = (
            f"<h2>OptionMargin Pre-Option Audit: {company}</h2>"
            f"<p>Contract <strong>{html.escape(teaser.contract_piid)}</strong> ({agency}, UEI: {html.escape(teaser.prospect_uei)}) "
            f"is {teaser.days_until_option} days from Option Exercise ({teaser.next_option_date.isoformat()}).</p>"
            f"<p><strong>Estimated Annual FAR 52.222-43 Recovery: ${teaser.estimated_annual_recovery_usd:,.2f}</strong> "
            f"(WD {html.escape(teaser.wd_number)} Rev {teaser.old_revision} -> Rev {teaser.new_revision}; 0.00% OH/G&A/Profit).</p>"
            f"{poc_html}"
            f"<p><a href='{checkout_url}'>Unlock Full Audit-Ready Evidence Package ($1,499)</a></p>"
        )
        text_body = " ".join(
            part
            for part in (
                teaser.redacted_evidence_preview,
                poc_text,
                f"Checkout: {checkout.checkout_url}",
            )
            if part
        )
        idemp_key = f"PROSPECT-EMAIL-{teaser.contract_piid}-REV{teaser.new_revision}"
        verified = poc is not None and poc.resolution_source == "SAM_GOV_ENTITY_API"
        channel, status = self._send_if_configured(
            recipient_email,
            subject,
            html_body,
            text_body,
            external_email=poc.poc_email if poc else None,
            external_verified=verified,
        )
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
    def _send_if_configured(
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        external_email: str | None = None,
        external_verified: bool = False,
    ) -> tuple[str, str]:
        smtp_result = _send_via_gmail_smtp(
            to_email,
            subject,
            html_body,
            text_body,
            external_email=external_email,
            external_verified=external_verified,
        )
        if smtp_result is not None:
            return smtp_result
        resend_key = os.getenv("RESEND_API_KEY", "").strip()
        if resend_key:
            try:
                from_addr = os.getenv("EMAIL_FROM", "OptionMargin <onboarding@resend.dev>")
                deliver_to = to_email
                if "onboarding@resend.dev" in from_addr:
                    deliver_to = AUDIT_INBOX
                payload = json.dumps(
                    {
                        "from": from_addr,
                        "to": [deliver_to],
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


def _live_external_enabled() -> bool:
    return os.getenv("OUTBOUND_LIVE_MODE", "").strip().lower() in {"1", "true", "yes"}


def _compose_links(poc_email: str, subject: str, body: str) -> tuple[str, str]:
    query_subject = urllib.parse.quote(subject)
    query_body = urllib.parse.quote(body[:1500])
    mailto = f"mailto:{urllib.parse.quote(poc_email)}?subject={query_subject}&body={query_body}"
    gmail_url = (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={urllib.parse.quote(poc_email)}&su={query_subject}&body={query_body}"
    )
    return mailto, gmail_url


def _send_via_gmail_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    external_email: str | None = None,
    external_verified: bool = False,
) -> tuple[str, str] | None:
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "").strip()
    if not (host and user and password):
        return None
    try:
        port = int(os.getenv("SMTP_PORT", "465") or "465")
    except ValueError:
        port = 465
    external_ok = bool(
        external_verified
        and _live_external_enabled()
        and external_email
        and "@" in external_email
        and external_email.lower() != AUDIT_INBOX
    )
    message = EmailMessage()
    message["From"] = user
    message["Subject"] = subject
    envelope = [AUDIT_INBOX]
    if external_ok:
        message["To"] = external_email
        message["Bcc"] = AUDIT_INBOX
        envelope = [external_email, AUDIT_INBOX]
    else:
        message["To"] = AUDIT_INBOX
        if external_email and external_email.lower() != AUDIT_INBOX:
            message["X-OptionMargin-POC"] = external_email
        envelope = [AUDIT_INBOX]
    message.set_content(text_body or subject)
    message.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            smtp.login(user, password)
            smtp.send_message(message, to_addrs=envelope)
        return "GMAIL_SMTP_SSL", "SENT_LIVE"
    except (smtplib.SMTPException, OSError, TimeoutError):
        return None
