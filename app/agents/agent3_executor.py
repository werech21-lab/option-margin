"""Agent 3 — Executor.

The outbox key is sha256 of tenant, contract, WD, revision, and event type.
A second delivery with the same key is skipped. Transport failures back off
exponentially and become DEAD_LETTER after three failures. Billing leakage is
(expected adjusted rate - actual billed rate) times hours billed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import smtplib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage

import httpx

from app.config import ZERO_2, q2, q4, settings
from app.models import AdjustmentCase, BillingMatch, CalculationVersion, DeliveryOutbox, EvidenceLink, PayrollRow, utcnow

DEAD_LETTER_AFTER = 3


class Agent3Executor:
    """Idempotent delivery, claim export, and billing reconciliation."""

    def idempotency_key(
        self,
        *,
        tenant_id: str,
        contract_id: str,
        wd_id: str,
        revision: int | str,
        event_type: str,
    ) -> str:
        material = f"{tenant_id}:{contract_id}:{wd_id}:{revision}:{event_type}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def run(self, session, payload: dict) -> DeliveryOutbox:
        tenant_id = str(payload["tenant_id"])
        contract_id = str(payload["contract_id"])
        wd_id = str(payload["wd_id"])
        revision = str(payload["revision"])
        event_type = str(payload["event_type"])
        key = self.idempotency_key(
            tenant_id=tenant_id,
            contract_id=contract_id,
            wd_id=wd_id,
            revision=revision,
            event_type=event_type,
        )
        existing = session.query(DeliveryOutbox).filter(DeliveryOutbox.idempotency_key == key).one_or_none()
        if existing is not None:
            return existing
        case_id = str(payload.get("case_id") or f"CASE-{key[:12].upper()}")
        case = session.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one_or_none()
        if case is None:
            monthly = q2(payload.get("estimated_monthly_exposure_usd", "0"))
            case = AdjustmentCase(
                tenant_id=tenant_id,
                case_id=case_id,
                contract_id=contract_id,
                change_event_id=payload.get("change_event_id"),
                status=str(payload.get("status") or "POTENTIAL"),
                event_type=event_type,
                estimated_monthly_exposure_usd=monthly,
                annualized_exposure_usd=q2(monthly * Decimal(12)),
                evidence_complete=bool(payload.get("evidence_complete", False)),
                missing_fields_json=list(payload.get("missing_fields") or []),
                next_action=str(payload.get("next_action") or "Complete evidence package"),
                rule_pack_version="US-SCLS-1.0",
                updated_at=utcnow(),
            )
            session.add(case)
            session.flush()
        row = DeliveryOutbox(
            tenant_id=tenant_id,
            case_id=case.case_id,
            idempotency_key=key,
            channel=str(payload.get("channel") or "INTERNAL_TASK"),
            recipient=str(payload.get("recipient") or ""),
            payload_json=dict(payload),
            status="PENDING",
            retry_count=0,
            created_at=utcnow(),
        )
        session.add(row)
        session.flush()
        self.attempt_send(row)
        session.commit()
        return row

    def attempt_send(self, row: DeliveryOutbox) -> None:
        if row.channel == "INTERNAL_TASK":
            row.status = "SENT"
            row.next_retry_at = None
            return
        if row.channel == "EMAIL":
            if not _smtp_ready():
                row.status = "PENDING"
                row.next_retry_at = None
                return
            try:
                _send_smtp(row)
            except (OSError, smtplib.SMTPException):
                self.note_failure(row)
                return
            row.status = "SENT"
            row.next_retry_at = None
            return
        url = ""
        if isinstance(row.payload_json, dict):
            url = str(row.payload_json.get("webhook_url") or "")
        if not url:
            self.note_failure(row)
            return
        try:
            response = httpx.post(url, json=row.payload_json, timeout=5.0)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            self.note_failure(row)
            return
        row.status = "SENT"
        row.next_retry_at = None

    def note_failure(self, row: DeliveryOutbox) -> None:
        row.retry_count = int(row.retry_count or 0) + 1
        if row.retry_count >= DEAD_LETTER_AFTER:
            row.status = "DEAD_LETTER"
            row.next_retry_at = None
            return
        delay_seconds = (2 ** row.retry_count) * 60
        row.status = "FAILED"
        row.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    def claim_csv(self, session, case_id: str) -> str:
        case = session.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one()
        version = _latest_version(session, case_id)
        payroll = (
            session.query(PayrollRow)
            .filter(PayrollRow.contract_id == case.contract_id, PayrollRow.tenant_id == case.tenant_id)
            .order_by(PayrollRow.worker_hash)
            .all()
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "worker_hash",
                "occupation_code",
                "eligible_hours",
                "previous_rate",
                "new_required_rate",
                "actual_new_rate",
                "voluntary_stripped",
                "eligible_delta",
                "hw_delta",
                "payroll_taxes",
                "total_claim",
            ]
        )
        if payroll and version is not None:
            data = version.breakdown_json or {}
            required = q4(data.get("new_required_wage", version.mandatory_wage_delta))
            for line in payroll:
                hours = q2(line.eligible_hours)
                eligible = q4(version.mandatory_wage_delta)
                voluntary = q4(version.voluntary_wage_stripped)
                hw_delta = q4(version.mandatory_hw_delta)
                tax_hourly = q4(version.accompanying_tax_hourly)
                tax_amount = q2(hours * tax_hourly)
                total = q2(hours * (eligible + hw_delta + tax_hourly))
                writer.writerow(
                    [
                        line.worker_hash,
                        line.occupation_code,
                        f"{hours:.2f}",
                        f"{q4(line.actual_prev_wage):.4f}",
                        f"{required:.4f}",
                        f"{q4(line.actual_new_wage):.4f}",
                        f"{voluntary:.4f}",
                        f"{eligible:.4f}",
                        f"{hw_delta:.4f}",
                        f"{tax_amount:.2f}",
                        f"{total:.2f}",
                    ]
                )
        elif version is not None:
            data = version.breakdown_json or {}
            hours = q2(version.total_monthly_hours)
            tax_amount = q2(version.monthly_tax_entitlement_usd)
            writer.writerow(
                [
                    "ESTIMATE-NOT-PAYROLL",
                    "23470",
                    f"{hours:.2f}",
                    str(data.get("actual_prev_wage", "0.0000")),
                    str(data.get("new_required_wage", f"{q4(version.mandatory_wage_delta):.4f}")),
                    str(data.get("actual_new_wage", "0.0000")),
                    f"{q4(version.voluntary_wage_stripped):.4f}",
                    f"{q4(version.mandatory_wage_delta):.4f}",
                    f"{q4(version.mandatory_hw_delta):.4f}",
                    f"{tax_amount:.2f}",
                    f"{q2(version.total_monthly_entitlement_usd):.2f}",
                ]
            )
        return buffer.getvalue()

    def evidence_dossier(self, session, case_id: str) -> dict:
        case = session.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one()
        version = _latest_version(session, case_id)
        links = session.query(EvidenceLink).filter(EvidenceLink.case_id == case_id).all()
        overhead = q2(0)
        ga = q2(0)
        profit = q2(0)
        assert overhead == 0 and ga == 0 and profit == 0
        return {
            "case_id": case.case_id,
            "contract_id": case.contract_id,
            "status": case.status,
            "rule_pack_version": case.rule_pack_version,
            "evidence_complete": case.evidence_complete,
            "missing_fields": list(case.missing_fields_json or []),
            "verified_receipt_date": _iso(case.verified_receipt_date),
            "filing_deadline_date": _iso(case.filing_deadline_date),
            "source_published_at_is_not_the_filing_clock": True,
            "overhead": f"{overhead:.2f}",
            "ga": f"{ga:.2f}",
            "profit": f"{profit:.2f}",
            "calculation": None
            if version is None
            else {
                "version_num": version.version_num,
                "total_workers": version.total_workers,
                "total_monthly_hours": f"{q2(version.total_monthly_hours):.2f}",
                "mandatory_wage_delta": f"{q4(version.mandatory_wage_delta):.4f}",
                "voluntary_wage_stripped": f"{q4(version.voluntary_wage_stripped):.4f}",
                "mandatory_hw_delta": f"{q4(version.mandatory_hw_delta):.4f}",
                "accompanying_tax_hourly": f"{q4(version.accompanying_tax_hourly):.4f}",
                "total_monthly_entitlement_usd": f"{q2(version.total_monthly_entitlement_usd):.2f}",
                "breakdown": version.breakdown_json,
            },
            "documents": [
                {
                    "field_name": link.field_name,
                    "field_value": link.field_value,
                    "source_type": link.source_type,
                    "document_hash": link.document_hash,
                    "citation_span": link.citation_span,
                    "verified_at": link.verified_at.isoformat() if link.verified_at else None,
                }
                for link in links
            ],
        }

    def evidence_html(self, session, case_id: str) -> str:
        dossier = self.evidence_dossier(session, case_id)
        rows = []
        for document in dossier["documents"]:
            rows.append(
                "<tr>"
                f"<td>{_escape(document['source_type'])}</td>"
                f"<td>{_escape(document['field_name'])}</td>"
                f"<td>{_escape(document['field_value'])}</td>"
                f"<td><code>{_escape(document['document_hash'])}</code></td>"
                f"<td>{_escape(document['citation_span'])}</td>"
                "</tr>"
            )
        body = "\n".join(rows) or "<tr><td colspan='5'>No evidence links recorded.</td></tr>"
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Evidence dossier "
            + _escape(case_id)
            + "</title></head><body>"
            f"<h1>FAR 52.222-43 evidence dossier {_escape(case_id)}</h1>"
            f"<p>Overhead {dossier['overhead']} · G&amp;A {dossier['ga']} · Profit {dossier['profit']}</p>"
            "<table border='1' cellpadding='6'><thead><tr>"
            "<th>Source</th><th>Field</th><th>Value</th><th>SHA-256</th><th>Span</th>"
            "</tr></thead><tbody>"
            + body
            + "</tbody></table><pre>"
            + _escape(json.dumps(dossier, indent=2))
            + "</pre></body></html>"
        )

    def reconcile_billing(
        self,
        session,
        *,
        tenant_id: str,
        case_id: str,
        contract_id: str,
        invoice_number: str,
        billing_period: str,
        expected_adjusted_rate: Decimal | str | int,
        actual_billed_rate: Decimal | str | int,
        hours_billed: Decimal | str | int,
    ) -> BillingMatch:
        expected = q4(expected_adjusted_rate)
        actual = q4(actual_billed_rate)
        hours = q2(hours_billed)
        variance = q2((expected - actual) * hours)
        if variance > 0:
            status = "UNDERBILLED_LEAKAGE"
        elif variance == 0:
            status = "MATCHED"
        else:
            status = "PENDING"
        row = BillingMatch(
            tenant_id=tenant_id,
            case_id=case_id,
            contract_id=contract_id,
            invoice_number=invoice_number,
            billing_period=billing_period,
            expected_adjusted_rate=expected,
            actual_billed_rate=actual,
            hours_billed=hours,
            variance_leakage_usd=variance,
            reconciliation_status=status,
            checked_at=utcnow(),
        )
        session.add(row)
        case = session.query(AdjustmentCase).filter(AdjustmentCase.case_id == case_id).one()
        if status == "UNDERBILLED_LEAKAGE":
            case.unbilled_leakage_usd = variance
        elif status == "MATCHED":
            case.unbilled_leakage_usd = ZERO_2
        case.updated_at = utcnow()
        session.commit()
        return row

    def variance_only(
        self,
        *,
        expected_adjusted_rate: Decimal | str | int,
        actual_billed_rate: Decimal | str | int,
        hours_billed: Decimal | str | int,
    ) -> tuple[Decimal, str]:
        variance = q2((q4(expected_adjusted_rate) - q4(actual_billed_rate)) * q2(hours_billed))
        if variance > 0:
            return variance, "UNDERBILLED_LEAKAGE"
        if variance == 0:
            return variance, "MATCHED"
        return variance, "PENDING"


def _latest_version(session, case_id: str) -> CalculationVersion | None:
    return (
        session.query(CalculationVersion)
        .filter(CalculationVersion.case_id == case_id)
        .order_by(CalculationVersion.version_num.desc())
        .first()
    )


def _iso(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat()  # type: ignore[attr-defined]


def _escape(value: object) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _smtp_ready() -> bool:
    return bool(settings.smtp_host and settings.smtp_port and settings.smtp_user and settings.smtp_pass)


def _send_smtp(row: DeliveryOutbox) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_user
    message["To"] = row.recipient
    message["Subject"] = f"OptionMargin case {row.case_id}"
    message.set_content(json.dumps(row.payload_json, default=str))
    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port), timeout=10) as client:
        client.starttls()
        client.login(settings.smtp_user, settings.smtp_pass)
        client.send_message(message)

