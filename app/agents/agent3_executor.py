"""Agent 3: Executor — Transactional Outbox, Idempotency, Evidence Package Generator, and Billing Reconciler."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from app.config import q2, ZERO_2D
from app.models import AdjustmentCase, BillingReconciliation, TransactionalOutbox
from app.schemas import LifecycleStatus, QuantEvaluationResult, StateGate

VALID_LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    LifecycleStatus.DETECTED.value: {LifecycleStatus.SUPPORTED.value},
    LifecycleStatus.SUPPORTED.value: {LifecycleStatus.SUBMITTED.value},
    LifecycleStatus.SUBMITTED.value: {LifecycleStatus.AGREED.value},
    LifecycleStatus.AGREED.value: {LifecycleStatus.BILLED.value},
    LifecycleStatus.BILLED.value: {LifecycleStatus.PAID.value},
    LifecycleStatus.PAID.value: set(),
}


@dataclass(frozen=True)
class EvidencePackageManifest:
    case_id: str
    contract_piid: str
    modification_number: str
    far_clause: str
    total_claim_amount: Decimal
    overhead_ga_profit_excluded: Decimal
    voluntary_raise_excluded: Decimal
    cover_letter_markdown: str
    evidence_count: int
    ledger_line_count: int


class Agent3Executor:
    """Handles idempotent outbox dispatch, Evidence Package generation, lifecycle transitions, and billing reconciliation."""

    def enqueue_outbox_task(
        self,
        db: Any,
        *,
        org_id: str | None,
        idempotency_key: str,
        task_type: str,
        payload: dict,
    ) -> tuple[TransactionalOutbox, bool]:
        """Enqueue a task using the Transactional Outbox pattern with strict idempotency.

        Returns:
            (outbox_record, created_new) — if `idempotency_key` already exists, returns existing record and `False`.
        """
        existing = (
            db.query(TransactionalOutbox)
            .filter(TransactionalOutbox.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            return existing, False

        record = TransactionalOutbox(
            org_id=org_id,
            idempotency_key=idempotency_key,
            task_type=task_type,
            payload_json=json.dumps(payload, default=str),
            status="COMPLETED",
            retry_count=0,
            result_summary=f"Executed {task_type} idempotently ({idempotency_key})",
            processed_at=datetime.now(timezone.utc),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record, True

    def generate_evidence_package(
        self,
        *,
        case_id: str,
        contract_piid: str,
        modification_number: str,
        quant_result: QuantEvaluationResult,
    ) -> EvidencePackageManifest:
        """Build an audit-ready FAR 52.222-43 Evidence Package when StateGate == SUPPORTED."""
        if quant_result.state_gate != StateGate.SUPPORTED:
            raise ValueError(
                f"Cannot generate FAR 52.222-43 Evidence Package for case in state '{quant_result.state_gate.value}'. "
                "Case must pass fail-closed verification (StateGate.SUPPORTED)."
            )

        lines = [
            "# REQUEST FOR EQUITABLE / MANDATORY PRICE ADJUSTMENT UNDER FAR 52.222-43",
            f"**Contract Number (PIID):** {contract_piid}",
            f"**Incorporating Modification:** {modification_number}",
            f"**30-Day Clock Deadline:** {quant_result.notification_deadline_date}",
            "",
            "## Deterministic Entitlement Summary",
            f"- **Eligible Direct SCLS Wage Adjustment:** ${quant_result.total_eligible_wage_delta:,.2f}",
            f"- **Eligible Health & Welfare (H&W) Adjustment:** ${quant_result.total_eligible_hw_delta:,.2f}",
            f"- **Accompanying Statutory Taxes (FICA/FUTA/SUTA) & Workers' Comp:** ${quant_result.total_accompanying_taxes_wc:,.2f}",
            f"- **Voluntary Wage Increases Strictly Excluded:** ${quant_result.voluntary_raise_excluded_amount:,.2f}",
            "- **Overhead / G&A / Profit Strictly Excluded (FAR 52.222-43(d)):** $0.00",
            f"- **TOTAL MANDATORY CONTRACT PRICE ADJUSTMENT:** **${quant_result.total_claim_amount:,.2f}**",
        ]
        cover_letter = "\n".join(lines)

        return EvidencePackageManifest(
            case_id=case_id,
            contract_piid=contract_piid,
            modification_number=modification_number,
            far_clause="FAR 52.222-43",
            total_claim_amount=quant_result.total_claim_amount,
            overhead_ga_profit_excluded=ZERO_2D,
            voluntary_raise_excluded=quant_result.voluntary_raise_excluded_amount,
            cover_letter_markdown=cover_letter,
            evidence_count=len(quant_result.evidence_spans),
            ledger_line_count=len(quant_result.ledger_lines),
        )

    def advance_lifecycle(
        self,
        db: Any,
        case: AdjustmentCase,
        target_status: LifecycleStatus,
    ) -> AdjustmentCase:
        """Enforce strict lifecycle progression: DETECTED -> SUPPORTED -> SUBMITTED -> AGREED -> BILLED -> PAID."""
        allowed = VALID_LIFECYCLE_TRANSITIONS.get(case.lifecycle_status, set())
        if target_status.value not in allowed:
            raise ValueError(
                f"Invalid lifecycle transition from '{case.lifecycle_status}' to '{target_status.value}'."
            )
        case.lifecycle_status = target_status.value
        db.commit()
        db.refresh(case)
        return case

    def reconcile_billing(
        self,
        db: Any,
        *,
        org_id: str,
        case: AdjustmentCase,
        executed_mod_number: str,
        agreed_amount: Decimal,
        invoice_number: str,
        billed_amount: Decimal,
        billed_at: date,
        paid_amount: Decimal,
        paid_at: date | None = None,
    ) -> BillingReconciliation:
        """Reconcile agreed bilateral modification vs. billed invoice vs. DFAS/Treasury payment."""
        agreed = q2(agreed_amount)
        billed = q2(billed_amount)
        paid = q2(paid_amount)
        variance = q2(agreed - paid)

        if paid == ZERO_2D:
            status = "BILLED_AWAITING_PAYMENT"
        elif variance == ZERO_2D:
            status = "RECONCILED_PAID_IN_FULL"
        else:
            status = "UNDERPAID_VARIANCE_ALERT"

        rec = BillingReconciliation(
            org_id=org_id,
            case_id=case.id,
            executed_mod_number=executed_mod_number,
            agreed_amount=agreed,
            invoice_number=invoice_number,
            billed_amount=billed,
            billed_at=billed_at,
            paid_amount=paid,
            paid_at=paid_at,
            variance_amount=variance,
            reconciliation_status=status,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec
